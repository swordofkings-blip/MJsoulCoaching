class TenpaiProbEstimator:
    def __init__(self, stats):
        self._stats = stats

    def estimate(self, player, game):
        if player.reach_state != "none":
            return 1
        else:
            num_remain_turns = game.num_pipais() // 4
            num_furos = len(player.furos)
            stat = self._stats.get('yamitenStats', {}).get(f'{num_remain_turns},{num_furos}')
            if stat:
                return stat['tenpai'] / stat['total']
            return 1
