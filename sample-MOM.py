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
from talib._ta_lib import MOM

from polofutures import RestClient, WsClient


_MAX_ROWS = 500
_LAST_TRADE = 0

# Account Keys
API_KEY = os.environ['PF_API_KEY']
SECRET = os.environ['PF_SECRET']
API_PASS = os.environ['PF_PASS']

# Trading parameters
SYMBOL = 'BTCUSDTPERP'
LEVERAGE = '25'
TRADE_SIZE = 5                              # Trade size in lots
MAX_SLIPPAGE = 0.025                        # Maximum slippage for market orders
SLOW_SIG = "INSERT SLOW SIGNAL SPAN"        # Set slow momentum signal speed, e.g. 16
FAST_SIG = "INSERT FAST SIGNAL SPAN"        # Set fast momentum signal speed, e.g. 4
RISK_LIMITS = {'short' : -500, 'long' : 500}

rest_client = RestClient(API_KEY, SECRET, API_PASS)

# Fetch Rest MarketData - Last 100 ticks
market = rest_client.market_api()
trade = rest_client.trade_api()

mkt_data = market.get_index_list(".PXBTUSDT", maxCount=100)['dataList']

# Cleanup historical data to match the ws stream
for d in mkt_data:
    del d['decomposionList']
    d['timestamp'] = d.pop('timePoint')
    d['price'] = d.pop('value')

'''
Create some OHLC data for technical analysis, and signalling of the algo
Set your timeframe 30S, 1M, 5M, etc. Note that longer timeframes will need a longer initialisation period
as we are dealing with tick data, and constructing our own candlesticks. We are attempting to create a fast acting trade bot'''


def ohlc(mkt_data, tf='15S'):
    if len(mkt_data) > _MAX_ROWS: mkt_data.pop(0)
    mkt_data_df = pd.DataFrame(mkt_data)
    mkt_data_df['price'] = mkt_data_df['price'].astype(float)
    mkt_data_df.index = pd.to_datetime(mkt_data_df['timestamp'], unit='ms')
    _ohlc = mkt_data_df['price'].resample(tf).ohlc()
    ohlc_df = _ohlc

    return ohlc_df


class Strategy:
    def __init__(self, ohlc_df):
        self.ohlc_df = ohlc_df
        self.signal = []
        self.position = trade.get_position_details(SYMBOL)
        self.close = self.ohlc_df['close'].values

    def dual_momentum(self, slow, fast):

        self.ohlc_df['SMOM'] = MOM(self.close, slow)
        self.ohlc_df['FMOM'] = MOM(self.close, fast)

    def trade_signal(self, slow, fast):
        '''
        Tweak trade signal or create strategies here
        This is a dual momentum strategy, if both fast and slow mometum signals are greater than zero we buy
        if both are lower than zero we sell'''
        self.dual_momentum(slow, fast)

        self.ohlc_df.loc[((self.ohlc_df['SMOM'] > 0) & (self.ohlc_df['FMOM'] > 0)), 'Signal'] = 'buy'
        self.ohlc_df.loc[((self.ohlc_df['SMOM'] < 0) & (self.ohlc_df['FMOM'] < 0)), 'Signal'] = 'sell'

        self.ohlc_df['Position'] = self.ohlc_df['Signal'].copy()
        self.ohlc_df['Position'].ffill(inplace=True)

        self.ohlc_df.fillna(0, inplace=True)
        self.execute_trade()
        self.trade_status()

    def execute_trade(self, MAX_SLIPPAGE=0.025):
        global _LAST_TRADE
        global RISK_LIMITS
        # Use the last known candle to trade, most recent is still forming.
        self.signal = self.ohlc_df.iloc[-2]

        # Using limit orders to control potential slippage
        if self.signal['Signal'] == 'sell' and _LAST_TRADE < self.signal.name.value:
            _LAST_TRADE = self.signal.name.value
            price = int(self.signal['close']*(1 - MAX_SLIPPAGE))
            if self.position["currentQty"] < RISK_LIMITS['short']:
                print(f'Short risk limit Exceeded {RISK_LIMITS["short"]}')
            else:
                order = trade.create_limit_order(symbol=SYMBOL, side=self.signal['Signal'], leverage=LEVERAGE, size=TRADE_SIZE,
                                                 price=str(price))

        elif self.signal['Signal'] == 'buy' and _LAST_TRADE < self.signal.name.value:
            _LAST_TRADE = self.signal.name.value
            price = int(self.signal['close'] * (1 + MAX_SLIPPAGE))
            if self.position["currentQty"] > RISK_LIMITS['long']:
                print(f'Long risk limit Exceeded {RISK_LIMITS["long"]}')
            else:
                order = trade.create_limit_order(symbol=SYMBOL, side=self.signal['Signal'], leverage=LEVERAGE, size=TRADE_SIZE,
                                                 price=str(price))

    def trade_status(self):
        # Trade status updates
        print(f'Latest Signals:\n '
              f'{self.ohlc_df.tail(5).to_string()}\n')
        print(f'Current Position:\n'
              f'Position {self.position["currentQty"]}\n'
              f'Entry Price {self.position["avgEntryPrice"]}\n'
              f'liquidation Price {self.position["liquidationPrice"]}\n'
              f'Unrealised Pnl {self.position["unrealisedRoePcnt"]*100}%\n')


def gen_signal(msg):
    if msg['topic'] == f'/contract/instrument:{SYMBOL}':
        new_ticks = msg["data"]
        new_ticks.pop('symbol', None)
        new_ticks['price'] = new_ticks.pop('indexPrice')
        mkt_data.append(new_ticks)

        # Setup the algo and run, ensure parameters are set
        try:
            ohlc_data = ohlc(mkt_data)
            strat = Strategy(ohlc_data)
            strat.trade_signal(SLOW_SIG, FAST_SIG)
        except Exception as e:
            print(f'Momentum Trader Error!\n'
                  f'Check Parameter Inputs\n {e}')


async def ws_stream():

    await ws_client.connect()
    await ws_client.subscribe(f'/contract/instrument:{SYMBOL}')


if __name__ == "__main__":
    print('Starting Momentum Trader!')
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

