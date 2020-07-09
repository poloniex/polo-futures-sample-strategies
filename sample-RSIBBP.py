# Copyright 2020 Polo Digital Assets, Ltd.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE

import os
import asyncio
import pandas as pd
from talib._ta_lib import RSI, BBANDS

from polofutures import RestClient, WsClient


MAX_ROWS = 500

# Account Keys
API_KEY = os.environ['PF_API_KEY']
SECRET = os.environ['PF_SECRET']
API_PASS = os.environ['PF_PASS']

# Trading parameters
SYMBOL = 'BTCUSDTPERP'
LEVERAGE = '25'
TRADE_SIZE = 50
MAX_SLIPPAGE = 0.025
RSI_SPAN = "SET RSI SPAN"    # RSI indicator span, e.g. 12
BB_SPAN = "SET BBAND SPAN"      # BB indicator span, e.g. 20

rest_client = RestClient(API_KEY, SECRET, API_PASS)

# Fetch Rest MarketData - Last 100 ticks
market = rest_client.market_api()
mkt_data = market.get_trade_history(SYMBOL)[::-1]
trade = rest_client.trade_api()
last_trade = 0

'''
Create some OHLC data for technical analysis, and signalling of the algo
Set your timeframe 30S, 1T, 5T, etc. Note that longer timeframes will need a longer initialisation period
as we are dealing with tick data, and constructing our own candlesticks'''

def ohlcv(mkt_data, tf='1T'):
    if len(mkt_data) > MAX_ROWS: mkt_data.pop(0)
    mkt_data_df = pd.DataFrame(mkt_data)
    mkt_data_df['price'] = mkt_data_df['price'].astype(float)

    mkt_data_df.index = pd.to_datetime(mkt_data_df['ts'], unit='ns')
    _ohlc = mkt_data_df['price'].resample(tf).ohlc()
    _vol = mkt_data_df['size'].resample(tf).sum()
    ohlcv_df = _ohlc.join(_vol).dropna()

    return ohlcv_df


class Strategy:
    def __init__(self, ohlcv_df):
        self.ohlcv_df = ohlcv_df
        self.signal = []
        self.position = trade.get_position_details(SYMBOL)
        self.close = self.ohlcv_df['close'].values

    def bbp(self, timeperiod, nbdevup=2, nbdevdn=2, matype=0):
        up, mid, low = BBANDS(self.close, timeperiod, nbdevup, nbdevdn, matype)
        self.ohlcv_df['BBP'] = (self.ohlcv_df['close'] - low) / (up - low)

    def rsif(self, timeperiod):
        self.ohlcv_df['RSI'] = RSI(self.close, timeperiod)

    def trade_signal(self, rsi_span, bb_span):
        '''
        Tweak trade signal or create strategies here
        This is an RSI and BBand trade strategy, when both give buy signal bot will long. Reverse for short
        Trades close based on RSI cooloff - this gives more leniency towards profit taking'''
        self.rsif(int(rsi_span))
        self.bbp(int(bb_span))

        self.ohlcv_df.loc[((self.ohlcv_df['RSI'] < 40) & (self.ohlcv_df['BBP'] < 0)), 'Signal'] = 'buy'
        self.ohlcv_df.loc[((self.ohlcv_df['RSI'] > 60) & (self.ohlcv_df['BBP'] > 1)), 'Signal'] = 'sell'

        self.ohlcv_df['Position'] = self.ohlcv_df['Signal'].copy()
        self.ohlcv_df['Position'].ffill(inplace=True)

        # Trade close condition on RSI 'cooloff'
        self.ohlcv_df.loc[((self.ohlcv_df['RSI'] > 60) & (self.ohlcv_df['Position'] == 'buy')), 'Signal'] = 'sell'
        self.ohlcv_df.loc[((self.ohlcv_df['RSI'] < 40) & (self.ohlcv_df['Position'] == 'sell')), 'Signal'] = 'buy'

        self.ohlcv_df.fillna(0, inplace=True)
        self.execute_trade()
        self.trade_status()

    def execute_trade(self, MAX_SLIPPAGE=0.025):
        global last_trade
        # Use the last known candle to trade, most recent is still forming.
        self.signal = self.ohlcv_df.iloc[-2]

        # Using limit orders to control potential slippage
        if self.signal['Signal'] == 'sell' and last_trade < self.signal.name.value:
            last_trade = self.signal.name.value
            price = int(self.signal['close']*(1 - MAX_SLIPPAGE))
            order = trade.create_limit_order(symbol=SYMBOL, side=self.signal['Signal'], leverage=LEVERAGE, size=TRADE_SIZE,
                                             price=str(price))

        elif self.signal['Signal'] == 'buy' and last_trade < self.signal.name.value:
            last_trade = self.signal.name.value
            price = int(self.signal['close'] * (1 + MAX_SLIPPAGE))
            order = trade.create_limit_order(symbol=SYMBOL, side=self.signal['Signal'], leverage=LEVERAGE, size=TRADE_SIZE,
                                             price=str(price))

    def trade_status(self):
        # Trade status updates
        print(f'Latest Signals:\n '
              f'{self.ohlcv_df.tail(5).to_string()}\n')
        print(f'Current Position:\n'
              f'Position {self.position["currentQty"]}\n'
              f'Entry Price {self.position["avgEntryPrice"]}\n'
              f'liquidation Price {self.position["liquidationPrice"]}\n'
              f'Unrealised Pnl {self.position["unrealisedRoePcnt"]*100}%\n')


def gen_signal(msg):
    if msg['topic'] == f'/contractMarket/execution:{SYMBOL}':
        # Bot needs to wait for executions before filling trade signals
        new_ticks = msg["data"]
        new_ticks.pop('symbol', None)
        mkt_data.append(new_ticks)

        try:
            ohlcv_data = ohlcv(mkt_data)
            strat = Strategy(ohlcv_data)
            strat.trade_signal(RSI_SPAN, BB_SPAN)
        except Exception as e:
            print(f'RSI-BBand Trader Error!\n'
                  f'Check Parameter Inputs\n {e}')


async def ws_stream():

    await ws_client.connect()
    await ws_client.subscribe(f'/contractMarket/execution:{SYMBOL}')


if __name__ == "__main__":
    print('Starting RSI-BBand Trader!')
    ws_client = WsClient(gen_signal, API_KEY, SECRET, API_PASS)
    loop = asyncio.get_event_loop()

    try:
        loop.create_task(ws_stream())
        loop.run_forever()
    except (KeyboardInterrupt, Exception) as e:
        print(f'Shutting Down {e}')
        loop.run_until_complete(ws_client.disconnect())
    finally:
        loop.close()