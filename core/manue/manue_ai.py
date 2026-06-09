import json
import os
import math
import random as _random

import numpy as np

from .pai import Pai
from .pai_set import PaiSet
from .shanten_analysis import ShantenAnalysis
from .bit_vector import BitVector
from .danger_estimator import DangerEstimator
from .tenpai_prob_estimator import TenpaiProbEstimator
from .prob_dist import ProbDist
from .hash_map import HashMap
from .furo import Furo
from . import util


class ManueAI:
    FURO_TYPE_TO_MENTSU_TYPE = {
        "chi": "shuntsu",
        "pon": "kotsu",
        "daiminkan": "kantsu",
        "kakan": "kantsu",
        "ankan": "kantsu",
    }

    ALL_PIDS = []
    for pid in range(Pai.NUM_IDS):
        for _ in range(4):
            ALL_PIDS.append(pid)

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), '..', '..')
        share_dir = os.path.join(base_dir, 'share')
        with open(os.path.join(share_dir, 'game_stats.json'), 'r', encoding='utf-8') as f:
            self._stats = json.load(f)
        try:
            with open(os.path.join(share_dir, 'light_game_stats.json'), 'r', encoding='utf-8') as f:
                light_stats = json.load(f)
            self._stats = util.merge_objects(self._stats, light_stats)
        except FileNotFoundError:
            pass
        self._danger_estimator = DangerEstimator(base_dir)
        self._tenpai_prob_estimator = TenpaiProbEstimator(self._stats)
        self._no_changes = [0, 0, 0, 0]

    def respond_to_action(self, action, player, game):
        if action.get('actor') == player.id:
            action_type = action.get('type')
            if action_type in ('tsumo', 'chi', 'pon', 'reach'):
                possible_actions = self._categorize_actions(action.get('possible_actions', []))
                if possible_actions['hora']:
                    return self._create_action(possible_actions['hora'])
                elif action_type == 'tsumo' and player.reach_state == 'accepted':
                    return self._create_action({'type': 'dahai', 'pai': action['pai'], 'tsumogiri': True})
                else:
                    decision = self._decide_dahai(
                        action.get('cannot_dahai', []),
                        player.reach_state == 'declared',
                        possible_actions['reach'],
                        player, game
                    )
                    if decision['reach']:
                        return self._create_action(possible_actions['reach'])
                    else:
                        tehais = player.tehais
                        last_tehai = tehais[-1] if tehais else None
                        tsumogiri = (action_type in ('tsumo', 'reach') and
                                     decision['dahai'] and last_tehai and
                                     decision['dahai'].has_same_symbol(last_tehai))
                        return self._create_action({
                            'type': 'dahai',
                            'pai': decision['dahai'],
                            'tsumogiri': tsumogiri
                        })
        else:
            action_type = action.get('type')
            if action_type in ('dahai', 'kakan'):
                possible_actions = self._categorize_actions(action.get('possible_actions', []))
                if possible_actions['hora']:
                    return self._create_action(possible_actions['hora'])
                elif possible_actions['furos']:
                    return self._decide_furo(possible_actions['furos'], player, game)
        return self._create_action({'type': 'none'})

    def _decide_dahai(self, forbidden_dahais, reach_declared, can_reach, player, game):
        metrics = self._get_metrics(forbidden_dahais, reach_declared, can_reach, player, game)
        key = self._choose_best_metric(metrics, True)
        action_idx, pai_str = key.split('.', 1)
        return {
            'dahai': Pai(pai_str),
            'shanten': metrics[key]['shanten'],
            'reach': int(action_idx) == 0,
        }

    def _get_metrics(self, forbidden_dahais, reach_declared, can_reach, player, game):
        cand_dahais = []
        for pai in player.tehais:
            if (util.all_(cand_dahais, lambda p: not p.equal(pai)) and
                    util.all_(forbidden_dahais, lambda p: not p.equal(pai))):
                cand_dahais.append(pai)

        pids = [pai.id() for pai in player.tehais]
        analysis = ShantenAnalysis(pids, {'allowed_extra_pais': 1})

        scenes = {}
        tenpai_probs = {}
        for p in game.players():
            if p != player:
                scenes[p.id] = self._danger_estimator.get_scene(game, player, p)
                tenpai_probs[p.id] = self._get_tenpai_prob(p, game)

        safe_probs = self._get_safe_probs(cand_dahais, player, game, scenes, tenpai_probs)
        imm_dists = self._get_immediate_score_changes_dists(cand_dahais, player, game, scenes, tenpai_probs)

        def compute(reach_mode):
            return self._get_metrics_internal(
                cand_dahais, analysis, safe_probs, imm_dists,
                player.tehais, player.furos, reach_mode, player, game)

        metrics = {}
        if can_reach:
            now_metrics = compute("now")
            now_metrics = self._select_tenpai_metrics(now_metrics)
            self._merge_metrics(metrics, 0, now_metrics)
            never_metrics = compute("never")
            self._merge_metrics(metrics, -1, never_metrics)
        else:
            reach_mode = "now" if reach_declared else "default"
            default_metrics = compute(reach_mode)
            if reach_declared:
                default_metrics = self._select_tenpai_metrics(default_metrics)
            self._merge_metrics(metrics, -1, default_metrics)
        return metrics

    def _merge_metrics(self, metrics, prefix, other_metrics):
        for key, metric in other_metrics.items():
            metrics[f"{prefix}.{key}"] = metric

    def _select_tenpai_metrics(self, metrics):
        return {k: v for k, v in metrics.items() if v['shanten'] <= 0}

    def _decide_furo(self, furo_actions, player, game):
        metrics = {}
        pids = [pai.id() for pai in player.tehais]
        analysis = ShantenAnalysis(pids, {'allowed_extra_pais': 1})
        scenes = {}
        tenpai_probs = {}
        for p in game.players():
            if p != player:
                scenes[p.id] = self._danger_estimator.get_scene(game, player, p)
                tenpai_probs[p.id] = self._get_tenpai_prob(p, game)

        none_metrics = self._get_metrics_internal(
            [None], analysis,
            self._get_safe_probs([None], player, game, scenes, tenpai_probs),
            self._get_immediate_score_changes_dists([None], player, game, scenes, tenpai_probs),
            player.tehais, player.furos, "default", player, game)
        metrics["none"] = none_metrics["none"]

        for j, action in enumerate(furo_actions):
            tehais = list(player.tehais)
            for pai in action.get('consumed', []):
                for i, t in enumerate(tehais):
                    if t.equal(pai):
                        tehais.pop(i)
                        break
            furos = list(player.furos) + [Furo(
                type_=action['type'],
                taken=Pai(action['pai']),
                consumed=[Pai(p) for p in action.get('consumed', [])],
                target=action.get('target')
            )]
            cand_dahais = []
            for pai in tehais:
                if (util.all_(cand_dahais, lambda p: not p.equal(pai)) and
                        not self._is_kuikae(action, pai)):
                    cand_dahais.append(pai)
            furo_metrics = self._get_metrics_internal(
                cand_dahais, analysis,
                self._get_safe_probs(cand_dahais, player, game, scenes, tenpai_probs),
                self._get_immediate_score_changes_dists(cand_dahais, player, game, scenes, tenpai_probs),
                tehais, furos, "default", player, game)
            self._merge_metrics(metrics, j, furo_metrics)

        key = self._choose_best_metric(metrics, False)
        if key == "none":
            return self._create_action({'type': 'none'})
        else:
            action_idx, _ = key.split('.', 1)
            return self._create_action(furo_actions[int(action_idx)])

    def _is_kuikae(self, furo_action, dahai):
        pais = furo_action.get('consumed', []) + [dahai.to_string()]
        pais.sort()
        if len(pais) >= 3:
            if pais[0] == pais[1] == pais[2]:
                return True
        return False

    def _get_metrics_internal(self, cand_dahais, analysis, safe_probs, imm_dists,
                               tehais, furos, reach_mode, player, game):
        metrics = self._get_hora_estimation(cand_dahais, analysis, tehais, furos, reach_mode, player, game)

        tenpai_ryukyoku_avg_pts = self._get_ryukyoku_average_points(True, player, game)
        noten_ryukyoku_avg_pts = self._get_ryukyoku_average_points(False, player, game)
        ryukyoku_prob = self._get_ryukyoku_prob(player, game)
        ryukyoku_prob_on_my_no_hora = ryukyoku_prob ** (3 / 4)

        score_changes_dist_on_ryukyoku_if_tenpai = self._get_score_changes_dist_on_ryukyoku(True, player, game)
        score_changes_dist_on_ryukyoku_if_noten = self._get_score_changes_dist_on_ryukyoku(False, player, game)
        score_changes_dists_on_other_hora = [
            self._get_random_hora_score_changes_dist(p, player, game)
            for p in game.players() if p != player
        ]

        for pai in cand_dahais:
            key = pai.to_string() if pai else "none"
            if key not in metrics:
                continue
            m = metrics[key]
            m['red'] = pai and pai.red()
            m['safe_prob'] = safe_probs[key]
            m['hoju_prob'] = 1 - m['safe_prob']
            m['safe_expected_points'] = m['safe_prob'] * m['expected_hora_points']
            m['unsafe_expected_points'] = -(1 - m['safe_prob']) * 6265
            m['ryukyoku_prob'] = ryukyoku_prob
            m['ryukyoku_average_points'] = tenpai_ryukyoku_avg_pts if m['shanten'] <= 0 else noten_ryukyoku_avg_pts
            m['ryukyoku_expected_points'] = m['safe_prob'] * ryukyoku_prob * m['ryukyoku_average_points']

            m['immediate_score_changes_dist'] = imm_dists[key]
            m['score_changes_dist_on_ryukyoku'] = (
                score_changes_dist_on_ryukyoku_if_tenpai if m['shanten'] <= 0
                else score_changes_dist_on_ryukyoku_if_noten)
            m['score_changes_dist_on_hora'] = self._get_score_changes_dist_on_hora(m, player, game)

            m['ryukyoku_prob'] = (1 - m['hora_prob']) * ryukyoku_prob_on_my_no_hora
            m['others_hora_prob'] = (1 - m['hora_prob']) * (1 - ryukyoku_prob_on_my_no_hora)

            my_hora_item = (m['score_changes_dist_on_hora'], m['hora_prob'])
            ryukyoku_item = (m['score_changes_dist_on_ryukyoku'], m['ryukyoku_prob'])
            other_hora_items = [(d, m['others_hora_prob'] / 3) for d in score_changes_dists_on_other_hora]

            m['future_score_changes_dist'] = ProbDist.merge([my_hora_item, ryukyoku_item] + other_hora_items)
            m['score_changes_dist'] = m['immediate_score_changes_dist'].replace(
                self._no_changes, m['future_score_changes_dist'])
            m['expected_points'] = m['score_changes_dist'].expected()[player.id]
            m['average_rank'] = self._get_average_rank(m['score_changes_dist'], player, game)

        return metrics

    def _get_score_changes_dist_on_hora(self, metric, player, game):
        tsumo_hora_prob = self._stats.get('numTsumoHoras', 0) / max(1, self._stats.get('numHoras', 1))
        unit_dist_map = HashMap()
        for target in game.players():
            if target != player:
                changes = [0, 0, 0, 0]
                changes[player.id] = 1
                changes[target.id] = -1
            elif player == game.oya():
                changes = [-1/3, -1/3, -1/3, -1/3]
                changes[player.id] = 1
            else:
                changes = [-1/4, -1/4, -1/4, -1/4]
                changes[player.id] = 1
                if game.oya():
                    changes[game.oya().id] = -1/2
            prob = tsumo_hora_prob if target == player else (1 - tsumo_hora_prob) / 3
            unit_dist_map.set(changes, prob)
        return ProbDist.mult(metric['hora_points_dist'], ProbDist(unit_dist_map))

    def _get_ryukyoku_average_points(self, self_tenpai, player, game):
        noten_ryukyoku_tenpai_prob = self._get_noten_ryukyoku_tenpai_prob(player, game)
        ryukyoku_tenpai_probs = []
        for i in range(4):
            p = game.players()[i]
            if p == player:
                current_tenpai_prob = 1 if self_tenpai else 0
            else:
                current_tenpai_prob = self._get_tenpai_prob(p, game)
            ryukyoku_tenpai_probs.append(current_tenpai_prob * 1 + (1 - current_tenpai_prob) * noten_ryukyoku_tenpai_prob)

        result = 0
        for i in range(2 ** 4):
            tenpais = [(i & (2 ** j)) != 0 for j in range(4)]
            prob = 1
            num_tenpais = 0
            for j in range(4):
                prob *= ryukyoku_tenpai_probs[j] if tenpais[j] else (1 - ryukyoku_tenpai_probs[j])
                if tenpais[j]:
                    num_tenpais += 1
            if prob > 0:
                if tenpais[player.id]:
                    points = 0 if num_tenpais == 4 else 3000 / num_tenpais
                else:
                    points = 0 if num_tenpais == 0 else -3000 / (4 - num_tenpais)
                result += prob * points
        return result

    def _get_score_changes_dist_on_ryukyoku(self, self_tenpai, player, game):
        noten_ryukyoku_tenpai_prob = self._get_noten_ryukyoku_tenpai_prob(player, game)
        tenpais_dist = ProbDist([0, 0, 0, 0])
        for p in game.players():
            if p == player:
                current_tenpai_prob = 1 if self_tenpai else 0
            else:
                current_tenpai_prob = self._get_tenpai_prob(p, game)
            ryukyoku_tenpai_prob = current_tenpai_prob * 1 + (1 - current_tenpai_prob) * noten_ryukyoku_tenpai_prob
            tenpais = [1 if pp == p else 0 for pp in game.players()]
            dist = ProbDist(HashMap([
                [[0, 0, 0, 0], 1 - ryukyoku_tenpai_prob],
                [tenpais, ryukyoku_tenpai_prob]
            ]))
            tenpais_dist = ProbDist.add(tenpais_dist, dist)
        return tenpais_dist.map_value(self._tenpais_to_ryukyoku_points)

    def _tenpais_to_ryukyoku_points(self, tenpais):
        num_tenpais = sum(1 for t in tenpais if t)
        if num_tenpais == 0 or num_tenpais == 4:
            return [0, 0, 0, 0]
        return [3000 / num_tenpais if t else -3000 / (4 - num_tenpais) for t in tenpais]

    def _get_noten_ryukyoku_tenpai_prob(self, player, game):
        noten_freq = self._stats.get('ryukyokuTenpaiStat', {}).get('noten', 1)
        tenpai_freq = 0
        tenpai_dist = self._stats.get('ryukyokuTenpaiStat', {}).get('tenpaiTurnDistribution', {})
        t = game.turn() + 0.25
        final_turn = 17.5
        while t <= final_turn:
            key = str(int(t)) if abs(t - round(t)) < 1e-10 else f"{t:.2f}".rstrip('0')
            tenpai_freq += tenpai_dist.get(key, 0)
            t += 0.25
        return tenpai_freq / (tenpai_freq + noten_freq) if (tenpai_freq + noten_freq) > 0 else 0

    def _choose_best_metric(self, metrics, prefer_black):
        best_key = None
        best_metric = None
        for key, metric in metrics.items():
            if best_key is None or self._compare_metric(metric, best_metric, prefer_black) < 0:
                best_key = key
                best_metric = metric
        return best_key

    def _compare_metric(self, lhs, rhs, prefer_black):
        if lhs['average_rank'] < rhs['average_rank']:
            return -1
        if lhs['average_rank'] > rhs['average_rank']:
            return 1
        if lhs['expected_points'] > rhs['expected_points']:
            return -1
        if lhs['expected_points'] < rhs['expected_points']:
            return 1
        if prefer_black:
            if not lhs.get('red') and rhs.get('red'):
                return -1
            if lhs.get('red') and not rhs.get('red'):
                return 1
        return 0

    def _get_safe_probs(self, cand_dahais, player, game, scenes, tenpai_probs):
        safe_probs = {}
        for pai in cand_dahais:
            key = pai.to_string() if pai else "none"
            safe_probs[key] = 1
        for p in game.players():
            if p != player:
                scene = scenes[p.id]
                tenpai_prob = tenpai_probs[p.id]
                for pai in cand_dahais:
                    if pai:
                        if scene.anpai(pai):
                            safe_prob = 1
                        else:
                            prob_info = self._danger_estimator.estimate_prob(scene, pai)
                            safe_prob = 1 - tenpai_prob * prob_info['prob']
                        safe_probs[pai.to_string()] *= safe_prob
                    else:
                        safe_probs["none"] = 1
        return safe_probs

    def _get_immediate_score_changes_dists(self, cand_dahais, player, game, scenes, tenpai_probs):
        score_changes_dists = {}
        for pai in cand_dahais:
            key = pai.to_string() if pai else "none"
            score_changes_dists[key] = ProbDist(self._no_changes)

        for hora_player in game.players():
            if hora_player != player:
                scene = scenes[hora_player.id]
                tenpai_prob = tenpai_probs[hora_player.id]
                hora_points_freqs = (self._stats.get('oyaHoraPointsFreqs', {})
                                    if hora_player == game.oya()
                                    else self._stats.get('koHoraPointsFreqs', {}))
                items = []
                total = hora_points_freqs.get('total', 1)
                for points_str, freq in hora_points_freqs.items():
                    if points_str == "total":
                        continue
                    items.append([int(points_str), freq / total])
                hora_points_dist = ProbDist(HashMap(items))

                hoju_changes = [0, 0, 0, 0]
                hoju_changes[hora_player.id] = 1
                hoju_changes[player.id] = -1

                for pai in cand_dahais:
                    key = pai.to_string() if pai else "none"
                    if pai:
                        if scene.anpai(pai):
                            hoju_prob = 0
                        else:
                            prob_info = self._danger_estimator.estimate_prob(scene, pai)
                            hoju_prob = tenpai_prob * prob_info['prob']
                        unit_dist = ProbDist(HashMap([[hoju_changes, hoju_prob], [self._no_changes, 1 - hoju_prob]]))
                        score_changes_dists[key] = score_changes_dists[key].replace(
                            self._no_changes, ProbDist.mult(hora_points_dist, unit_dist)
                        )
        return score_changes_dists

    def _get_random_hora_score_changes_dist(self, actor, player, game):
        hora_points_freqs = (self._stats.get('oyaHoraPointsFreqs', {})
                            if actor == game.oya()
                            else self._stats.get('koHoraPointsFreqs', {}))
        items = []
        total = hora_points_freqs.get('total', 1)
        for points_str, freq in hora_points_freqs.items():
            if points_str == "total":
                continue
            items.append([int(points_str), freq / total])
        hora_points_dist = ProbDist(HashMap(items))
        return ProbDist.mult(hora_points_dist, self._get_hora_factors_dist(actor, player, game))

    def _get_hora_factors_dist(self, actor, player, game):
        tsumo_hora_prob = self._stats.get('numTsumoHoras', 0) / max(1, self._stats.get('numHoras', 1))
        m = HashMap()
        for target in game.players():
            prob = tsumo_hora_prob if target == player else (1 - tsumo_hora_prob) / 3
            m.set(self._get_hora_factors(actor, target, player, game), prob)
        return ProbDist(m)

    def _get_hora_factors(self, actor, target, player, game):
        if target == actor:
            if actor == game.oya():
                return [1 if p == actor else -1/3 for p in game.players()]
            else:
                return [1 if p == actor else (-1/2 if p == game.oya() else -1/4) for p in game.players()]
        else:
            return [1 if p == actor else (-1 if p == target else 0) for p in game.players()]

    def _get_tenpai_prob(self, player, game):
        if player.reach_state != "none":
            return 1
        num_remain_turns = game.num_pipais() // 4
        num_furos = len(player.furos)
        stat = self._stats.get('yamitenStats', {}).get(f'{num_remain_turns},{num_furos}')
        if stat:
            return stat['tenpai'] / stat['total']
        return 1

    def _get_hora_estimation(self, cand_dahais, analysis, tehais, furos, reach_mode, player, game):
        goals = []
        for goal in analysis.goals:
            if reach_mode == "now" and goal['shanten'] > 0:
                continue
            if analysis.shanten > 3 and goal['shanten'] > analysis.shanten:
                continue
            goal['furos'] = furos
            self._calculate_fan(goal, tehais, reach_mode, player, game)
            if goal['points'] > 0:
                goals.append(goal)

        visible_pai_set = PaiSet(game.visible_pais(player))
        invisible_pai_set = PaiSet.get_all()
        invisible_pai_set.remove_pai_set(visible_pai_set)
        invisible_pids = np.array([pai.id() for pai in invisible_pai_set.to_pais()], dtype=np.int32)

        num_tsumos = self._get_num_expected_remaining_turns(player, game)
        num_tries = 1000

        n_pids = Pai.NUM_IDS
        total_hora = np.zeros(n_pids + 1, dtype=np.int32)
        total_points = np.zeros(n_pids + 1, dtype=np.int32)
        total_freqs = [{} for _ in range(n_pids + 1)]

        rng = np.random.default_rng(42)
        draws = rng.integers(0, len(invisible_pids), size=(num_tries, max(num_tsumos, 1)))
        drawn_ids = invisible_pids[draws]
        eye = np.eye(n_pids, dtype=np.int32)
        tsumo_counts = eye[drawn_ids].sum(axis=1)
        tsumo_has = np.stack([tsumo_counts >= l for l in range(1, 5)], axis=1)

        shanten_vector = np.full(n_pids + 1, float('inf'))
        shanten_vector[n_pids] = analysis.shanten

        if not goals:
            metrics = {}
            for pai in cand_dahais:
                pid = pai.id() if pai else n_pids
                key = pai.to_string() if pai else "none"
                metrics[key] = {
                    'hora_prob': 0, 'average_hora_points': 0,
                    'hora_points_dist': ProbDist(HashMap([[0, 1]])),
                    'expected_hora_points': 0, 'shanten': shanten_vector[pid],
                }
            return metrics

        n_goals = len(goals)
        req_vecs = np.zeros((n_goals, 4, n_pids), dtype=bool)
        thr_vecs = np.zeros((n_goals, n_pids), dtype=bool)
        pts_arr = np.zeros(n_goals, dtype=np.int32)
        for gi, g in enumerate(goals):
            rv = np.array(g['required_vector'], dtype=np.int32)
            for li in range(4):
                req_vecs[gi, li] = rv >= (li + 1)
            thr_vecs[gi] = np.array(g['throwable_vector'], dtype=bool)
            pts_arr[gi] = g['points']
            for pid in range(n_pids):
                if g['throwable_vector'][pid] > 0 and g['shanten'] < shanten_vector[pid]:
                    shanten_vector[pid] = g['shanten']

        total_hora = np.zeros(n_pids + 1, dtype=np.int32)
        total_pts = np.zeros(n_pids + 1, dtype=np.int32)
        total_freqs = [{} for _ in range(n_pids + 1)]

        all_achieved = np.all(tsumo_has[:, np.newaxis, :, :] >= req_vecs[np.newaxis, :, :, :], axis=(2, 3))
        achieved_goals = [np.where(all_achieved[ti])[0] for ti in range(num_tries)]

        for ti in range(num_tries):
            if len(achieved_goals[ti]) == 0:
                continue
            a_thr = thr_vecs[achieved_goals[ti]]
            a_pts = pts_arr[achieved_goals[ti]]
            hora_mask = np.zeros(n_pids + 1, dtype=bool)
            hora_mask[:n_pids] = np.any(a_thr, axis=0)
            hora_mask[n_pids] = True
            best_pts = np.zeros(n_pids + 1, dtype=np.int32)
            for pid in np.where(hora_mask[:n_pids])[0]:
                cand = a_pts[a_thr[:, pid]]
                if len(cand):
                    best_pts[pid] = cand.max()
            best_pts[n_pids] = a_pts.max()

            for pid in np.where(hora_mask)[0]:
                total_hora[pid] += 1
                total_pts[pid] += int(best_pts[pid])
                p = int(best_pts[pid])
                total_freqs[pid][p] = total_freqs[pid].get(p, 0) + 1

        metrics = {}
        for pai in cand_dahais:
            pid = pai.id() if pai else n_pids
            key = pai.to_string() if pai else "none"
            hc = int(total_hora[pid])
            metrics[key] = {
                'hora_prob': hc / num_tries,
                'average_hora_points': (int(total_points[pid]) / hc if hc > 0 else 0),
                'hora_points_dist': ProbDist(HashMap(
                    [[pts, freq / hc] for pts, freq in total_freqs[pid].items()]
                    if hc > 0 else [[0, 1]]
                )),
                'expected_hora_points': int(total_points[pid]) / num_tries,
                'shanten': float(shanten_vector[pid]),
            }
        return metrics

    def _count_vector_to_bit_vectors(self, count_vector):
        bit_vectors = []
        for i in range(1, 5):
            bit_vectors.append(BitVector([c >= i for c in count_vector]))
        return bit_vectors

    def _calculate_fan(self, goal, tehais, reach_mode, player, game):
        mentsus = []
        for m in goal.get('mentsus', []):
            if isinstance(m, tuple):
                mentsus.append({
                    'type': m[0],
                    'pais': [Pai(pid) for pid in m[1:]]
                })
            else:
                mentsus.append({
                    'type': m['type'],
                    'pais': [Pai(pid) for pid in m['pids']]
                })
        for furo in goal.get('furos', []):
            mentsus.append({
                'type': self.FURO_TYPE_TO_MENTSU_TYPE.get(furo.type, furo.type),
                'pais': furo.pais()
            })

        all_pais = []
        for m in mentsus:
            all_pais.extend(m['pais'])
        furo_pais = []
        for furo in goal.get('furos', []):
            furo_pais.extend(furo.pais())

        goal['yakus'] = []
        goal['fan'] = 0

        if reach_mode != "never":
            self._add_yaku(goal, "reach", 1, 0)

        tanyaochu = not any(p.is_yaochu() for p in all_pais)
        if tanyaochu:
            self._add_yaku(goal, "tyc", 1)

        chantaiyao = all(
            any(p.is_yaochu() for p in m['pais'])
            for m in mentsus
        )
        if chantaiyao:
            self._add_yaku(goal, "cty", 2, 1)

        pinfu = all(
            m['type'] == "shuntsu" or
            (m['type'] == "toitsu" and game.yakuhai_fan(m['pais'][0], player) == 0)
            for m in mentsus
        )
        if pinfu:
            self._add_yaku(goal, "pf", 1, 0)

        yakuhai_fan = 0
        for m in mentsus:
            if m['type'] in ('kotsu', 'kantsu'):
                yakuhai_fan += game.yakuhai_fan(m['pais'][0], player)
        self._add_yaku(goal, "ykh", yakuhai_fan)

        ipeko = any(
            m1['type'] == "shuntsu" and
            any(
                m2['type'] == "shuntsu" and m2 != m1 and m2['pais'][0].has_same_symbol(m1['pais'][0])
                for m2 in mentsus
            )
            for m1 in mentsus
        )
        if ipeko:
            self._add_yaku(goal, "ipk", 1, 0)

        sanshoku_dojun = any(
            m1['type'] == "shuntsu" and
            all(
                any(
                    m2['type'] == "shuntsu" and m2['pais'][0].type() == t and m2['pais'][0].number() == m1['pais'][0].number()
                    for m2 in mentsus
                )
                for t in ["m", "p", "s"]
            )
            for m1 in mentsus
        )
        if sanshoku_dojun:
            self._add_yaku(goal, "ssj", 2, 1)

        ikki_tsukan = any(
            all(
                any(
                    m['type'] == "shuntsu" and m['pais'][0].type() == t and m['pais'][0].number() == n
                    for m in mentsus
                )
                for n in [1, 4, 7]
            )
            for t in ["m", "p", "s"]
        )
        if ikki_tsukan:
            self._add_yaku(goal, "ikt", 2, 1)

        toitoiho = all(m['type'] != "shuntsu" for m in mentsus)
        if toitoiho:
            self._add_yaku(goal, "tth", 2)

        chiniso = any(
            all(m['pais'][0].type() == t for m in mentsus)
            for t in ["m", "p", "s"]
        )
        honiso = any(
            all(m['pais'][0].type() == t or m['pais'][0].type() == "t" for m in mentsus)
            for t in ["m", "p", "s"]
        )
        if chiniso:
            self._add_yaku(goal, "cis", 6, 5)
        elif honiso:
            self._add_yaku(goal, "his", 3, 2)

        if goal['fan'] > 0:
            doras = game.doras()
            num_doras = sum(
                1 for pai in all_pais for dora in doras if pai.has_same_symbol(dora)
            )
            self._add_yaku(goal, "dr", num_doras)

        goal['fu'] = 30 if pinfu or len(goal.get('furos', [])) > 0 else 40
        goal['points'] = self._get_points(goal['fu'], goal['fan'], player == game.oya())

    def _add_yaku(self, goal, name, menzen_fan, kui_fan=None):
        if kui_fan is None:
            kui_fan = menzen_fan
        fan = menzen_fan if len(goal.get('furos', [])) == 0 else kui_fan
        if fan > 0:
            goal['yakus'].append([name, fan])
            goal['fan'] += fan

    def _get_points(self, fu, fan, oya):
        if fan >= 13:
            base_points = 8000
        elif fan >= 11:
            base_points = 6000
        elif fan >= 8:
            base_points = 4000
        elif fan >= 6:
            base_points = 3000
        elif fan >= 5 or (fan >= 4 and fu >= 40) or (fan >= 3 and fu >= 70):
            base_points = 2000
        elif fan >= 1:
            base_points = fu * (2 ** (fan + 2))
        else:
            base_points = 0
        return math.ceil(base_points * (6 if oya else 4) / 100) * 100

    def _get_num_expected_remaining_turns(self, player, game):
        current_turn = round(game.turn())
        num = 0
        den = 0
        turns_dist = self._stats.get('numTurnsDistribution', [])
        for i in range(current_turn, len(turns_dist)):
            prob = turns_dist[i]
            num += prob * (i - current_turn + 0.5)
            den += prob
        return round(num / den) if den > 0 else 0

    def _get_ryukyoku_prob(self, player, game):
        current_turn = int(game.turn())
        den = 0
        turns_dist = self._stats.get('numTurnsDistribution', [])
        for i in range(current_turn, len(turns_dist)):
            den += turns_dist[i]
        return self._stats.get('ryukyokuRatio', 0.1) / den if den > 0 else 0

    def _categorize_actions(self, actions):
        result = {'hora': None, 'reach': None, 'furos': []}
        for action in actions or []:
            if action.get('type') == 'hora':
                result['hora'] = action
            elif action.get('type') == 'reach':
                result['reach'] = action
            else:
                result['furos'].append(action)
        return result

    def _get_average_rank(self, score_changes_dist, player, game):
        my_id = player.id
        wins_dist = ProbDist([0, 0, 0, 0])
        for other in game.players():
            if other == player:
                continue
            win_prob = self._get_win_prob(score_changes_dist, other, player, game)
            d = ProbDist(HashMap([
                [[0, 0, 0, 0], 1 - win_prob],
                [[1 if i == other.id else 0 for i in range(4)], win_prob]
            ]))
            wins_dist = ProbDist.add(wins_dist, d)

        def calc_rank(wins):
            return 4 - sum(1 for w in wins if w == 1)
        rank_dist = wins_dist.map_value(calc_rank)
        return rank_dist.expected()

    def _get_win_prob(self, score_changes_dist, other, player, game):
        my_id = player.id
        my_pos = game.get_distance(player, game.chicha())
        other_pos = game.get_distance(other, game.chicha())
        next_kyoku = game.next_kyoku()
        key = f"{next_kyoku['bakaze']}{next_kyoku['kyoku_num']},{my_pos},{other_pos}"
        win_probs = self._stats.get('winProbsMap', {}).get(key, {})

        def calc_relative(score_changes):
            return (player.score + score_changes[my_id]) - (other.score + score_changes[other.id])
        relative_score_dist = score_changes_dist.map_value(calc_relative)

        win_prob = 0
        def process_rel(relative_score, prob):
            nonlocal win_prob
            win_prob += prob * self._get_win_prob_from_relative_score(relative_score, win_probs, my_pos, other_pos)
        relative_score_dist.dist.for_each(process_rel)
        return win_prob

    def _get_win_prob_from_relative_score(self, relative_score, win_probs, my_pos, other_pos):
        if win_probs and str(relative_score) in win_probs:
            return win_probs[str(relative_score)]
        if my_pos < other_pos:
            return 1 if relative_score >= 0 else 0
        else:
            return 1 if relative_score > 0 else 0

    def _create_action(self, action):
        return action
