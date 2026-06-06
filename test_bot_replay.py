# -*- coding: utf-8 -*-
import os
import sys
import pickle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from my_bot import MyBot
from sdk import MajsoulHandler
from liqi import LiqiProto


def replay_with_bot(filename: str):
    if not os.path.isfile(filename):
        print(f'[test] file not found: {filename}')
        return
    bot = MyBot(gui=None, think_time_sec=0.0)
    bot._auto_discard_enabled = False
    liqi = LiqiProto()
    history = pickle.load(open(filename, 'rb'))
    print(f'[test] loaded {len(history)} frames from {filename}')
    for i, flow_msg in enumerate(history):
        try:
            result = liqi.parse(flow_msg)
            bot.parse(result)
        except Exception as e:
            print(f'[test] frame {i} error: {e}')
    print('[test] final hand:', bot.state.my_hand)
    print('[test] final scores:', bot.state.scores)
    print('[test] doras:', bot.state.doras)
    print('[test] reach states:', [rs.is_reach for rs in bot.state.reach_states])
    print('[test] tsumo count:', bot.state.tsumo_count)
    return bot


if __name__ == '__main__':
    path = os.path.join(HERE, 'ws_dump.pkl')
    replay_with_bot(path)
