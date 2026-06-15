import json, random, copy, os, time, glob, sys, multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tools.extract_mismatches import process_file

def _eval_worker(args):
    """
    @title 個体とレコードの評価ワーカー
    @description 1つの個体パラメータと1つのレコードファイルに対して評価を実行し、一致率算出用のカウントを返します。
    @param {tuple} args - (pop_idx, record_path, params)
    @returns {tuple} (pop_idx, total_discard, discard_match, total_meld, meld_match)
    """
    pop_idx, path, params = args
    import sys, os
    # 子プロセス（spawn）用にパスを明示的に解決します。
    project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    from tools.extract_mismatches import process_file
    try:
        # process_fileは (lines, total_discard, discard_match, total_meld, meld_match, fname) を返します。
        res = process_file(path, params)
        _, td, dm, tm, mm, _ = res
        return (pop_idx, td, dm, tm, mm)
    except Exception as e:
        # 例外発生時はそのレコードでの評価を0として扱い、プロセスをクラッシュさせずに継続します。
        print(f"Error evaluating pop {pop_idx} on {os.path.basename(path)}: {e}")
        return (pop_idx, 0, 0, 0, 0)


# 遺伝子パラメータの探索境界定義
# 各項目のタプルは (最小値, 最大値, 型) を表します。
# メンバーシップ関数の閾値や幅、および副露防衛の閾値を最適化対象に設定しています。
GENE_DEFS = {
    # 基礎の何切るスコア計算パラメータ
    'UKEIRE_MULTIPLIER': (2, 10, int),
    'SHANTEN_MULTIPLIER': (50, 300, int),
    'SCORE_WALL_SUJI': (400, 1000, int),
    'SCORE_MUSUJI_PER_REACH': (-400, 0, int),
    'SCORE_GENBUTSU': (800, 1200, int),
    'DENNO_DANGER_SCALE': (10000, 20000, int),
    'SCORE_HONOR': (100, 500, int),
    'FURITEN_PENALTY': (100, 500, int),
    'MATAGI_PENALTY': (0, 300, int),
    'PENALTY_6BLOCK_MAINTAIN': (30, 150, int),
    'PENALTY_SHANTEN_BACKWARD': (500, 2000, int),
    'PENALTY_STANDARD_SHANTEN_BACKWARD': (0, 500, int),
    'AKA_KEEP_BONUS': (-100, 0, int),
    'ISOLATED_MIDDLE_BONUS': (5, 40, int),
    'HONOR_DISCARD_BONUS': (5, 50, int),
    'SLIM_WEAK_BLOCK_BONUS': (10, 100, int),
    'GOOD_SHAPE_CHANGE_BONUS': (0, 30, int),
    'BLOCK_COMPETITION_PENALTY': (0, 10, int),
    'SAFE_TILE_TURN_START': (3, 12, int),
    'SAFE_TILE_RAMP_DURATION': (5, 20, int),

    # 進行度（シャンテン数）に応じた基礎攻撃力
    'BASE_ATTACK_MAX_SHANTEN': (4, 6, int),
    'BASE_ATTACK_TENPAI_HIGH': (0.8, 1.0, float),
    'BASE_ATTACK_TENPAI_LOW': (0.5, 0.9, float),
    'BASE_ATTACK_1SHANTEN': (0.2, 0.6, float),
    'BASE_ATTACK_2SHANTEN': (0.05, 0.40, float),
    'BASE_ATTACK_3SHANTEN': (0.01, 0.20, float),
    'BASE_ATTACK_4SHANTEN': (0.005, 0.10, float),

    # リーチ判断パラメータ
    'RIICHI_BASE': (0.3, 0.9, float),
    'RIICHI_WAIT_WEIGHT': (0.5, 2.0, float),
    'RIICHI_OPP_REACH_PENALTY': (-0.8, 0.0, float),
    'RIICHI_DORA_PENALTY': (-0.3, 0.0, float),
    'RIICHI_LATE_PENALTY': (-0.5, 0.0, float),
    'RIICHI_LAST_RANK_BONUS': (0.0, 0.5, float),

    # 新ファジィ推論パラメータ（手牌価値Yと場の脅威度Xのメンバーシップ境界）
    'FUZZY_Y_LOW_BOUND': (0.05, 0.25, float),
    'FUZZY_Y_MED_PEAK': (0.15, 0.35, float),
    'FUZZY_Y_MED_WIDTH': (0.15, 0.45, float),
    'FUZZY_Y_HIGH_BOUND': (0.20, 0.40, float),
    'FUZZY_X_LOW_BOUND': (0.20, 0.60, float),
    'FUZZY_X_MED_PEAK': (0.40, 0.70, float),
    'FUZZY_X_MED_WIDTH': (0.15, 0.45, float),
    'FUZZY_X_HIGH_BOUND': (0.50, 0.90, float),
    'FUZZY_VAL_ALPHA': (0.70, 0.99, float),
    'FUZZY_VAL_BETA': (0.70, 0.99, float),
    'FUZZY_VAL_GAMMA': (0.40, 0.80, float),
    'FUZZY_SLIM_DEFENSE_WEIGHT': (0.005, 0.08, float),

    # 副露防衛判定パラメータ (expand_params で yaku_strategy.meld_defense に展開)
    'meld_defense_riichi_penalty_per_tile': (100, 600, int),
    'meld_defense_threat_penalty_per_tile': (50, 400, int),
    'meld_defense_min_defense_weight': (0.05, 0.50, float),
    'meld_defense_absolute_threshold': (150, 600, int),
    'meld_defense_conditional_threshold': (50, 400, int),
    'meld_defense_conditional_push_min': (0.4, 0.90, float),

    # 人読み: 対戦相手の統計デフォルト値
    'OPPONENT_DEFAULT_CALL_RATE': (0.15, 0.55, float),
    'OPPONENT_DEFAULT_WIN_RATE': (0.10, 0.35, float),
    'OPPONENT_DEFAULT_DAMATEN_RATE': (0.05, 0.80, float),
    'OPPONENT_DEFAULT_DEAL_IN_RATE': (0.05, 0.25, float),
    'OPPONENT_DEFAULT_RIICHI_RATE': (0.10, 0.35, float),

    # ダマテン警戒
    'THREAT_DAMA_SCALE': (0.05, 0.50, float),
    'DAMATEN_BASE_PENALTY': (50, 500, int),
}

STATE_FILE = 'ga_state.json'


def expand_params(flat_params: dict, base_params: dict) -> dict:
    """
    @title フラットパラメータの階層展開
    @description フラットな遺伝子パラメータを、ネストされた元の config_parameters.json の辞書構造に展開します。
    @param {dict} flat_params - フラットな遺伝子パラメータ
    @param {dict} base_params - ベースとなる元の全パラメータ
    @returns {dict} 展開後の階層型パラメータ辞書
    """
    expanded = copy.deepcopy(base_params)
    for k, v in flat_params.items():
        if k.startswith('meld_defense_'):
            sub_key = k[len('meld_defense_'):]
            if 'yaku_strategy' not in expanded:
                expanded['yaku_strategy'] = {}
            if 'meld_defense' not in expanded['yaku_strategy']:
                expanded['yaku_strategy']['meld_defense'] = {}
            expanded['yaku_strategy']['meld_defense'][sub_key] = v
        else:
            expanded[k] = v
    return expanded


def mutate(params: dict, rate: float = 0.3, size: float = 0.15) -> dict:
    """
    @title 突然変異処理
    @description 各遺伝子座について一定確率で突然変異（微小変動）を起こします。
    @param {dict} params - 元のフラットパラメータ
    @param {float} rate - 突然変異確率
    @param {float} size - 突然変異の探索幅スケール
    @returns {dict} 突然変異適用後のパラメータ
    """
    new = dict(params)
    for key, (mn, mx, typ) in GENE_DEFS.items():
        # 0.5 は突然変異の増減方向を決めるための中央値です。
        if random.random() > rate:
            continue
        cur = new.get(key, mn if typ == int else (mn + mx) / 2)
        if typ == int:
            d = int((mx - mn) * size * (random.random() - 0.5) * 2)
            new[key] = max(mn, min(mx, cur + d))
        else:
            d = (mx - mn) * size * (random.random() - 0.5) * 2
            # 3は小数点以下の丸め桁数です。
            new[key] = round(max(mn, min(mx, cur + d)), 3)
    return new


def crossover(parent1: dict, parent2: dict) -> dict:
    """
    @title 遺伝子の一様交叉
    @description 2つの親個体からランダムに遺伝子を引き継ぎ、新しい個体を生成します。
    @param {dict} parent1 - 親個体1
    @param {dict} parent2 - 親個体2
    @returns {dict} 交叉後の子個体パラメータ
    """
    child = {}
    for key in GENE_DEFS.keys():
        # 0.5は親1と親2から遺伝子を引き継ぐ確率の閾値です。
        if random.random() < 0.5:
            child[key] = parent1[key]
        else:
            child[key] = parent2[key]
    return child


def evaluate_fitness(params: dict, record_paths: list[str]) -> float:
    """
    @title フィットネス評価
    @description 与えられた全レコードに対し、並列で打牌一致率（60%）と副露一致率（40%）の加重平均を算出します。
    @param {dict} params - 階層展開されたパラメータ
    @param {list[str]} record_paths - 評価用レコードファイルのパスリスト
    @returns {float} 加重平均された適合度（0.0 ~ 1.0）
    """
    n_workers = multiprocessing.cpu_count()
    args_list = [(0, path, params) for path in record_paths]
    
    total_td = total_dm = total_tm = total_mm = 0
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        # as_completedを用いてリアルタイムに進捗を表示します。
        futures = [executor.submit(_eval_worker, args) for args in args_list]
        total_tasks = len(futures)
        completed = 0
        results = []
        for fut in as_completed(futures):
            results.append(fut.result())
            completed += 1
            # 2個ずつ、または最後に出力します。2は表示更新の閾値です。
            if completed % 2 == 0 or completed == total_tasks:
                sys.stdout.write(f"\r  Baseline evaluating... {completed}/{total_tasks} ({completed/total_tasks*100:.0f}%)")
                sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

        for _, td, dm, tm, mm in results:
            total_td += td
            total_dm += dm
            total_tm += tm
            total_mm += mm
            
    # 0.6 と 0.4 は打牌一致率と副露一致率のバランスを取るための加重係数です。
    discard_rate = total_dm / total_td if total_td > 0 else 0.0
    meld_rate = total_mm / total_tm if total_tm > 0 else 0.0
    return 0.6 * discard_rate + 0.4 * meld_rate



def save_state(pop: list, gen: int, log, cache: dict) -> None:
    """
    @title 世代状態の保存
    @description 中断からの復帰のために、現在の個体群、世代数、評価キャッシュをJSONファイルに書き出します。
    @param {list} pop - 個体群リスト
    @param {int} gen - 現在の世代数
    @param {file} log - ログファイルオブジェクト
    @param {dict} cache - 評価済みパラメータのキャッシュ
    """
    state = {'gen': gen, 'pop': [(f, p) for f, p in pop], 'cache': cache}
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    log.write(f'State saved at gen {gen}\n')
    log.flush()


def load_state() -> tuple[int, list, dict]:
    """
    @title 世代状態の復帰
    @description 保存されたJSONファイルから、以前の中断時の状態と評価キャッシュをロードします。
    @returns {tuple} (世代数, 個体群リスト, 評価キャッシュ)
    """
    with open(STATE_FILE, encoding='utf-8') as f:
        state = json.load(f)
    return state['gen'], [(f, p) for f, p in state['pop']], state.get('cache', {})


def main():
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    data_dir = os.path.join(base_dir, 'data')
    all_records = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))
    
    # 1つおきにデータを間引き、6ファイルをトレーニング対象とすることで実用的な速度を確保します。
    # 最終的な検証には全11ファイルを使用します。
    train_records = all_records[::2]

    # 本番用設定ファイルをベースパラメータとして読み込みます。
    base_path = os.path.join(base_dir, 'config', 'config_parameters.json')
    with open(base_path, encoding='utf-8') as f:
        base_params = json.load(f)

    # フラットな初期個体を作成するための辞書を構築します。
    # GENE_DEFSに含まれるものはそこからデフォルトを取得し、残りは config_parameters.json からそのまま引き継ぎます。
    init_flat = {}
    for k in GENE_DEFS.keys():
        if k.startswith('meld_defense_'):
            sub_key = k[len('meld_defense_'):]
            val = base_params.get('yaku_strategy', {}).get('meld_defense', {}).get(sub_key, None)
        else:
            val = base_params.get(k, None)
        if val is None:
            # config_parametersにキーがない場合のフォールバック値（境界の中央値）です。
            mn, mx, typ = GENE_DEFS[k]
            val = int((mn + mx) / 2) if typ == int else round((mn + mx) / 2, 3)
        init_flat[k] = val

    resume_from = len(sys.argv) > 1 and sys.argv[1] == '--resume'
    extra_gens = 0
    pop_size = 24 # 24は標準的な個体数（CPUの並列度と世代探索のバランス値）です。
    arg_idx = 2
    if resume_from and len(sys.argv) > arg_idx:
        try:
            extra_gens = int(sys.argv[arg_idx])
            arg_idx += 1
        except:
            pass
    if len(sys.argv) > arg_idx:
        try:
            pop_size = int(sys.argv[arg_idx])
        except:
            pass
    start_gen = 0
    # エリートとして次代に残す優秀個体数（個体数の約1/6）
    keep = max(2, pop_size // 6)
    generations = 30 + extra_gens

    log_file = 'ga_result.log'
    fitness_cache = {}

    with open(log_file, 'a', encoding='utf-8') as log:
        if resume_from and os.path.exists(STATE_FILE):
            start_gen, pop, fitness_cache = load_state()
            target_size = max(pop_size, len(pop))
            while len(pop) < target_size:
                # 3はエリート親から選出するための上位範囲の除算数です。
                parent = random.choice(pop[:max(1, len(pop)//3)])[1]
                # 0.4と0.2は突然変異の確率と幅のスケールです。
                pop.append((0.0, mutate(parent, 0.4, 0.2)))
            pop_size = len(pop)
            keep = max(2, pop_size // 6)
            log.write(f'Resumed from gen {start_gen}, pop={pop_size}\n')
            print(f'Resumed from gen {start_gen}, pop={pop_size}', flush=True)
        else:
            base_fit = evaluate_fitness(base_params, train_records)
            log.write(f'Baseline Weighted Fitness: {base_fit*100:.2f}%\n')
            print(f'Baseline Weighted Fitness: {base_fit*100:.2f}%')
            
            # 初期ベースラインをキャッシュに登録
            init_key = json.dumps(init_flat, sort_keys=True)
            # ベースライン評価のtd, dm, tm, mmは直接手に入りませんが、再計算を防ぐために
            # フィットネス値のみダミーカウントとしてキャッシュに登録します。
            fitness_cache[init_key] = [base_fit, 0, 0, 0, 0]
            
            pop = [(base_fit, init_flat)]
            for _ in range(pop_size - 1):
                # 0.5と0.2は初期集団の初期変動用の突然変異パラメータです。
                pop.append((0.0, mutate(init_flat, 0.5, 0.2)))
            save_state(pop, 0, log, fitness_cache)

        # CPUコア数に基づいて並列プロセスを初期化します。
        n_workers = multiprocessing.cpu_count()
        executor = ProcessPoolExecutor(max_workers=n_workers)

        for gen in range(start_gen + 1, start_gen + generations + 1):
            t0 = time.time()
            need_eval = [i for i in range(pop_size) if pop[i][0] == 0.0]
            
            if need_eval:
                # 評価タスクを (pop_idx, record_path, params) の組み合わせで全生成し、並列実行します。
                args_list = []
                for idx in need_eval:
                    flat_p = pop[idx][1]
                    param_key = json.dumps(flat_p, sort_keys=True)
                    
                    # すでに過去の世代で同一パラメータが評価済みの場合は、キャッシュから引き戻して再計算をスキップします。
                    if param_key in fitness_cache:
                        fit, _, _, _, _ = fitness_cache[param_key]
                        pop[idx] = (fit, flat_p)
                    else:
                        expanded_p = expand_params(flat_p, base_params)
                        for rp in train_records:
                            args_list.append((idx, rp, expanded_p))
                
                if args_list:
                    # as_completedを用いて世代ごとの評価進捗をリアルタイム表示します。
                    futures = [executor.submit(_eval_worker, args) for args in args_list]
                    total_tasks = len(futures)
                    completed = 0
                    results = []
                    for fut in as_completed(futures):
                        results.append(fut.result())
                        completed += 1
                        # 10個完了ごと、または全タスク完了時に表示を更新します。10は更新閾値です。
                        if completed % 10 == 0 or completed == total_tasks:
                            sys.stdout.write(f"\r  Gen {gen} evaluating... {completed}/{total_tasks} ({completed/total_tasks*100:.0f}%)")
                            sys.stdout.flush()
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    
                    # 結果の集計 (実際に新規評価を行った個体のみが対象)
                    pop_results = {idx: {'td': 0, 'dm': 0, 'tm': 0, 'mm': 0} for idx in need_eval if pop[idx][0] == 0.0}
                    for pop_idx, td, dm, tm, mm in results:
                        pop_results[pop_idx]['td'] += td
                        pop_results[pop_idx]['dm'] += dm
                        pop_results[pop_idx]['tm'] += tm
                        pop_results[pop_idx]['mm'] += mm
                    
                    # フィットネスの再計算とキャッシュへの登録
                    for idx in need_eval:
                        if pop[idx][0] != 0.0:
                            # キャッシュヒットした個体はスキップします。
                            continue
                        flat_p = pop[idx][1]
                        param_key = json.dumps(flat_p, sort_keys=True)
                        
                        res = pop_results[idx]
                        td, dm, tm, mm = res['td'], res['dm'], res['tm'], res['mm']
                        discard_rate = dm / td if td > 0 else 0.0
                        meld_rate = mm / tm if tm > 0 else 0.0
                        # 0.6 / 0.4 の加重平均フィットネスを各個体にセット
                        fit = 0.6 * discard_rate + 0.4 * meld_rate
                        pop[idx] = (fit, flat_p)
                        
                        # 新規結果をキャッシュに登録します。
                        fitness_cache[param_key] = [fit, td, dm, tm, mm]

            pop.sort(key=lambda x: -x[0])
            msg = f'G{gen}: best={pop[0][0]*100:.2f}% ({time.time()-t0:.0f}s)'
            log.write(msg + '\n')
            log.flush()
            print(msg, flush=True)

            if gen % 10 == 0:
                save_state(pop, gen, log, fitness_cache)
                best_p = pop[0][1]
                # 進捗確認のため、主要な最適化パラメータの上位6個を画面表示します。
                # 6は画面幅に収めるための表示項目数制限です。
                for k in list(GENE_DEFS.keys())[:6]:
                    print(f'  {k}={best_p.get(k, "?")}', end='  ')
                print()

            # 世代が進むにつれて突然変異率（探索幅）を徐々に絞り込み、収束を促します。
            progress = (gen - start_gen) / generations
            # 0.05, 0.35, 0.18 は、探索の初期・終期幅を制御するアニーリング用のハイパーパラメータです。
            rate = max(0.05, 0.35 * (1 - progress))
            size = max(0.05, 0.18 * (1 - progress))
            nxt = pop[:keep]
            while len(nxt) < pop_size:
                # 0.7は交叉確率です。70%の確率で優秀な2つの親を掛け合わせ（ブレンドし）、30%は単一親の突然変異のみとします。
                if random.random() < 0.7 and len(pop[:keep]) >= 2:
                    p1 = random.choice(pop[:keep])[1]
                    p2_candidates = [p[1] for p in pop[:keep] if p[1] != p1]
                    p2 = random.choice(p2_candidates) if p2_candidates else p1
                    child = crossover(p1, p2)
                else:
                    child = random.choice(pop[:keep])[1]
                
                nxt.append((0.0, mutate(child, rate, size)))
            pop = nxt

        # 最終状態の保存とプロセスの終了
        save_state(pop, start_gen + generations, log, fitness_cache)
        executor.shutdown(wait=True)
        
        # 最終検証結果を出力
        log.write(f'\nValidation on all records:\n')
        best_expanded = expand_params(pop[0][1], base_params)
        bf = evaluate_fitness(base_params, all_records)
        gf = evaluate_fitness(best_expanded, all_records)
        log.write(f'Baseline: {bf*100:.2f}%\n')
        log.write(f'GA best:  {gf*100:.2f}%\n')
        print(f'Validation: base={bf*100:.2f}% ga={gf*100:.2f}%')
        
        if gf > bf:
            log.write('Improved!\n')
            best_path = 'ga_best.json'
            with open(best_path, 'w', encoding='utf-8') as f:
                json.dump(best_expanded, f, indent=2, ensure_ascii=False)
            print(f'Saved best parameters to {best_path}')

if __name__ == '__main__':
    main()
