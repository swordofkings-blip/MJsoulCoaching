import json
import os
from .pai import Pai
from .pai_set import PaiSet
from . import util


class Scene:
    def __init__(self, game, me, target):
        self._game = game
        self._me = me
        self._target = target
        self._tehai_set = PaiSet(me.tehais)
        self._anpai_set = PaiSet(game.anpais(target))
        self._visible_set = PaiSet(game.visible_pais(me))
        self._dora_set = PaiSet(game.doras())
        self._bakaze = game.bakaze()
        self._target_kaze = game.jikaze(target)

        prereach_sutehais = target.sutehais[:target.reach_sutehai_index + 1] if target.reach_sutehai_index >= 0 else []
        self._prereach_sutehai_set = PaiSet(prereach_sutehais)
        half = len(prereach_sutehais) // 2
        self._early_sutehai_set = PaiSet(prereach_sutehais[:half])
        self._late_sutehai_set = PaiSet(prereach_sutehais[half:])
        reach_pai = target.sutehais[target.reach_sutehai_index] if target.reach_sutehai_index >= 0 and target.reach_sutehai_index < len(target.sutehais) else None
        self._reach_pai_set = PaiSet([reach_pai] if reach_pai else [])

    def anpai(self, pai):
        return self._anpai_set.has(pai)

    def tsupai(self, pai):
        return pai.type() == "t"

    def suji(self, pai):
        return self._suji_of(pai, self._anpai_set)

    def weak_suji(self, pai):
        return self._weak_suji_of(pai, self._anpai_set)

    def reach_suji(self, pai):
        return self._weak_suji_of(pai, self._reach_pai_set)

    def prereach_suji(self, pai):
        return self._suji_of(pai, self._prereach_sutehai_set)

    def urasuji(self, pai):
        return self._urasuji_of(pai, self._prereach_sutehai_set)

    def early_urasuji(self, pai):
        return self._urasuji_of(pai, self._early_sutehai_set)

    def reach_urasuji(self, pai):
        return self._urasuji_of(pai, self._reach_pai_set)

    def aida4ken(self, pai):
        if pai.type() == "t":
            return False
        n = pai.number()
        t = pai.type()
        return ((2 <= n <= 5 and
                 self._prereach_sutehai_set.has(Pai(t, n - 1)) and
                 self._prereach_sutehai_set.has(Pai(t, n + 4))) or
                (5 <= n <= 8 and
                 self._prereach_sutehai_set.has(Pai(t, n - 4)) and
                 self._prereach_sutehai_set.has(Pai(t, n + 1))))

    def matagisuji(self, pai):
        return self._matagisuji_of(pai, self._prereach_sutehai_set)

    def early_matagisuji(self, pai):
        return self._matagisuji_of(pai, self._early_sutehai_set)

    def late_matagisuji(self, pai):
        return self._matagisuji_of(pai, self._late_sutehai_set)

    def reach_matagisuji(self, pai):
        return self._matagisuji_of(pai, self._reach_pai_set)

    def senkisuji(self, pai):
        return self._senkisuji_of(pai, self._prereach_sutehai_set)

    def early_senkisuji(self, pai):
        return self._senkisuji_of(pai, self._early_sutehai_set)

    def outer_prereach_sutehai(self, pai):
        return self._outer(pai, self._prereach_sutehai_set)

    def outer_early_sutehai(self, pai):
        return self._outer(pai, self._early_sutehai_set)

    def dora(self, pai):
        return self._dora_set.has(pai)

    def dora_suji(self, pai):
        return self._weak_suji_of(pai, self._dora_set)

    def dora_matagi(self, pai):
        return self._matagisuji_of(pai, self._dora_set)

    def fanpai(self, pai):
        return self._fanpai_fansu(pai) >= 1

    def ryenfonpai(self, pai):
        return self._fanpai_fansu(pai) >= 2

    def sangenpai(self, pai):
        return pai.type() == "t" and pai.number() >= 5

    def fonpai(self, pai):
        return pai.type() == "t" and pai.number() < 5

    def bakaze(self, pai):
        return pai.has_same_symbol(self._bakaze)

    def jikaze(self, pai):
        return pai.has_same_symbol(self._target_kaze)

    def _n_outer_prereach_sutehai(self, pai, n):
        if pai.type() == "t" or pai.number() == 5:
            return False
        n_inner_number = (pai.number() + n) if pai.number() < 5 else (pai.number() - n)
        if 1 <= n_inner_number <= 9:
            if (pai.number() < 5 and n_inner_number <= 5) or (pai.number() > 5 and n_inner_number >= 5):
                return self._prereach_sutehai_set.has(Pai(pai.type(), n_inner_number))
        return False

    def _n_or_more_of_neighbors_in_prereach_sutehais(self, pai, n, neighbor_distance):
        if pai.type() == "t":
            return False
        num_neighbors = sum(
            1 for nn in range(pai.number() - neighbor_distance, pai.number() + neighbor_distance + 1)
            if 1 <= nn <= 9 and self._prereach_sutehai_set.count(Pai(pai.type(), nn))
        )
        return num_neighbors >= n

    def _suji_of(self, pai, target_pai_set):
        if pai.type() == "t":
            return False
        return all(target_pai_set.has(Pai(pai.type(), n)) for n in self._get_suji_numbers(pai))

    def _weak_suji_of(self, pai, target_pai_set):
        if pai.type() == "t":
            return False
        return any(target_pai_set.has(Pai(pai.type(), n)) for n in self._get_suji_numbers(pai))

    def _get_suji_numbers(self, pai):
        return [n for n in [pai.number() - 3, pai.number() + 3] if 1 <= n <= 9]

    def _get_possible_sujis(self, pai):
        if pai.type() == "t":
            return []
        sujis = []
        for n in [pai.number() - 3, pai.number()]:
            if all(1 <= m <= 9 and not self._anpai_set.has(Pai(pai.type(), m))
                   for m in [n, n + 3]):
                sujis.append(Pai(pai.type(), n))
        return sujis

    def _n_chance_or_less(self, pai, n):
        if pai.type() == "t" or (4 <= pai.number() <= 6):
            return False
        for i in range(1, 3):
            kabe_pai = Pai(pai.type(), pai.number() + (i if pai.number() < 5 else -i))
            if self._visible_set.count(kabe_pai) >= 4 - n:
                return True
        return False

    def _num_n_or_inner(self, pai, n):
        return pai.type() != "t" and n <= pai.number() <= 10 - n

    def _visible_n_or_more(self, pai, n):
        return self._visible_set.count(pai) >= n

    def _urasuji_of(self, pai, target_pai_set):
        sujis = self._get_possible_sujis(pai)
        return any(
            (s.next(-1) and target_pai_set.has(s.next(-1))) or
            (s.next(4) and target_pai_set.has(s.next(4)))
            for s in sujis
        )

    def _senkisuji_of(self, pai, target_pai_set):
        sujis = self._get_possible_sujis(pai)
        return any(
            (s.next(-2) and target_pai_set.has(s.next(-2))) or
            (s.next(5) and target_pai_set.has(s.next(5)))
            for s in sujis
        )

    def _matagisuji_of(self, pai, target_pai_set):
        sujis = self._get_possible_sujis(pai)
        return any(
            (s.next(1) and target_pai_set.has(s.next(1))) or
            (s.next(2) and target_pai_set.has(s.next(2)))
            for s in sujis
        )

    def _outer(self, pai, target_pai_set):
        if pai.type() == "t" or pai.number() == 5:
            return False
        if pai.number() < 5:
            inner_numbers = list(range(pai.number() + 1, 6))
        else:
            inner_numbers = list(range(5, pai.number()))
        return any(target_pai_set.has(Pai(pai.type(), n)) for n in inner_numbers)

    def _fanpai_fansu(self, pai):
        return self._game.yakuhai_fan(pai, self._target)

    def chances_lte(self, i):
        return lambda pai: self._n_chance_or_less(pai, i)

    def visible_gte(self, i):
        return lambda pai: self._visible_n_or_more(pai, i + 1)

    def suji_visible_lte(self, i):
        def check(pai):
            if pai.type() == "t":
                return False
            return any(not self._visible_n_or_more(Pai(pai.type(), n), i + 1)
                      for n in self._get_suji_numbers(pai))
        return check

    def n_lte_n_lte(self, i):
        return lambda pai: self._num_n_or_inner(pai, i)

    def in_tehais_gte(self, i):
        return lambda pai: self._tehai_set.count(pai) >= i

    def suji_in_tehais_gte(self, i):
        def check(pai):
            if pai.type() == "t":
                return False
            return any(self._tehai_set.count(Pai(pai.type(), n)) >= i
                      for n in self._get_suji_numbers(pai))
        return check

    def neighbors_in_prereach_gte(self, i, j):
        return lambda pai: self._n_or_more_of_neighbors_in_prereach_sutehais(pai, j, i)

    def outer_prereach(self, i):
        return lambda pai: self._n_outer_prereach_sutehai(pai, i)

    def inner_prereach(self, i):
        return lambda pai: self._n_outer_prereach_sutehai(pai, -i)

    def same_type_in_prereach_gte(self, i):
        def check(pai):
            if pai.type() == "t":
                return False
            num_same_type = sum(1 for n in range(1, 10) if self._prereach_sutehai_set.has(Pai(pai.type(), n)))
            return num_same_type + 1 >= i
        return check


class DangerEstimator:
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), '..', '..')
        tree_path = os.path.join(base_dir, 'share', 'danger_tree.all.json')
        with open(tree_path, 'r', encoding='utf-8') as f:
            self._root = json.load(f)

    def get_scene(self, game, me, target):
        return Scene(game, me, target)

    def estimate_prob(self, scene, pai):
        pai = pai.remove_red()
        node = self._root
        features = []
        while node.get('feature_name'):
            feature_name = node['feature_name']
            value = self._evaluate_feature(scene, feature_name, pai)
            features.append({'name': feature_name, 'value': value})
            if value:
                node = node['positive']
            else:
                node = node['negative']
        return {'prob': node.get('average_prob', 0), 'features': features}

    def _evaluate_feature(self, scene, feature_name, pai):
        import re
        m = re.match(r'^chances<=(\d+)$', feature_name)
        if m:
            return scene.chances_lte(int(m.group(1)))(pai)
        m = re.match(r'^visible>=(\d+)$', feature_name)
        if m:
            return scene.visible_gte(int(m.group(1)))(pai)
        m = re.match(r'^sujiVisible<=(\d+)$', feature_name)
        if m:
            return scene.suji_visible_lte(int(m.group(1)))(pai)
        m = re.match(r'^(\d+)<=n<=(\d+)$', feature_name)
        if m:
            return scene.n_lte_n_lte(int(m.group(1)))(pai)
        m = re.match(r'^inTehais>=(\d+)$', feature_name)
        if m:
            return scene.in_tehais_gte(int(m.group(1)))(pai)
        m = re.match(r'^sujiInTehais>=(\d+)$', feature_name)
        if m:
            return scene.suji_in_tehais_gte(int(m.group(1)))(pai)
        m = re.match(r'^\+-(\d+)InPrereachSutehais>=(\d+)$', feature_name)
        if m:
            return scene.neighbors_in_prereach_gte(int(m.group(1)), int(m.group(2)))(pai)
        m = re.match(r'^(\d+)OuterPrereachSutehai$', feature_name)
        if m:
            return scene.outer_prereach(int(m.group(1)))(pai)
        m = re.match(r'^(\d+)InnerPrereachSutehai$', feature_name)
        if m:
            return scene.inner_prereach(int(m.group(1)))(pai)
        m = re.match(r'^sameTypeInPrereach>=(\d+)$', feature_name)
        if m:
            return scene.same_type_in_prereach_gte(int(m.group(1)))(pai)
        method_name = util.camel_case(feature_name)
        method = getattr(scene, method_name, None)
        if method and callable(method):
            return method(pai)
        return False
