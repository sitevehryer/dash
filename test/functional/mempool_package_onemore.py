#!/usr/bin/env python3
# Copyright (c) 2014-2020 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test descendant package tracking carve-out allowing one final transaction in
   an otherwise-full package as long as it has only one parent and is <= 10k in
   size.
"""

from decimal import Decimal

from test_framework.blocktools import COINBASE_MATURITY
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_raises_rpc_error, satoshi_round

MAX_ANCESTORS = 25
MAX_DESCENDANTS = 25

class MempoolPackagesTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.extra_args = [["-maxorphantxsize=100000"]]

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    # Build a transaction that spends parent_txid:vout
    # Return amount sent
    def chain_transaction(self, node, parent_txids, vouts, value, fee, num_outputs):
        send_value = satoshi_round((value - fee)/num_outputs)
        inputs = []
        for (txid, vout) in zip(parent_txids, vouts):
            inputs.append({'txid' : txid, 'vout' : vout})
        outputs = {}
        for _ in range(num_outputs):
            outputs[node.getnewaddress()] = send_value
        rawtx = node.createrawtransaction(inputs, outputs)
        signedtx = node.signrawtransactionwithwallet(rawtx)
        txid = node.sendrawtransaction(signedtx['hex'])
        fulltx = node.getrawtransaction(txid, 1)
        assert len(fulltx['vout']) == num_outputs  # make sure we didn't generate a change output
        return (txid, send_value)

    def run_test(self):
        # Mine some blocks and have them mature.
        self.nodes[0].generate(COINBASE_MATURITY + 1)
        utxo = self.nodes[0].listunspent(10)
        txid = utxo[0]['txid']
        vout = utxo[0]['vout']
        value = utxo[0]['amount']

        fee = Decimal("0.0002")
        # MAX_ANCESTORS transactions off a confirmed tx should be fine
        chain = []
        for _ in range(4):
            (txid, sent_value) = self.chain_transaction(self.nodes[0], [txid], [vout], value, fee, 2)
            vout = 0
            value = sent_value
            chain.append([txid, value])
        for _ in range(MAX_ANCESTORS - 4):
            (txid, sent_value) = self.chain_transaction(self.nodes[0], [txid], [0], value, fee, 1)
            value = sent_value
            chain.append([txid, value])
        (second_chain, second_chain_value) = self.chain_transaction(self.nodes[0], [utxo[1]['txid']], [utxo[1]['vout']], utxo[1]['amount'], fee, 1)

        # Check mempool has MAX_ANCESTORS + 1 transactions in it
        assert_equal(len(self.nodes[0].getrawmempool()), MAX_ANCESTORS + 1)

        # Adding one more transaction on to the chain should fail.
        assert_raises_rpc_error(-26, "too-long-mempool-chain, too many unconfirmed ancestors [limit: 25]", self.chain_transaction, self.nodes[0], [txid], [0], value, fee, 1)
        # ...even if it chains on from some point in the middle of the chain.
        assert_raises_rpc_error(-26, "too-long-mempool-chain, too many descendants", self.chain_transaction, self.nodes[0], [chain[2][0]], [1], chain[2][1], fee, 1)
        assert_raises_rpc_error(-26, "too-long-mempool-chain, too many descendants", self.chain_transaction, self.nodes[0], [chain[1][0]], [1], chain[1][1], fee, 1)
        # ...even if it chains on to two parent transactions with one in the chain.
        assert_raises_rpc_error(-26, "too-long-mempool-chain, too many descendants", self.chain_transaction, self.nodes[0], [chain[0][0], second_chain], [1, 0], chain[0][1] + second_chain_value, fee, 1)
        # ...especially if its > 40k weight
        assert_raises_rpc_error(-26, "too-long-mempool-chain, too many descendants", self.chain_transaction, self.nodes[0], [chain[0][0]], [1], chain[0][1], fee, 350)
        # But not if it chains directly off the first transaction
        self.chain_transaction(self.nodes[0], [chain[0][0]], [1], chain[0][1], fee, 1)
        # and the second chain should work just fine
        self.chain_transaction(self.nodes[0], [second_chain], [0], second_chain_value, fee, 1)

        # Finally, check that we added two transactions
        assert_equal(len(self.nodes[0].getrawmempool()), MAX_ANCESTORS + 3)

if __name__ == '__main__':
    MempoolPackagesTest().main()
