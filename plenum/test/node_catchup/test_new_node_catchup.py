from time import perf_counter

import pytest

from plenum.common.constants import DOMAIN_LEDGER_ID, LedgerState
from plenum.test.delayers import cr_delay
from plenum.test.spy_helpers import get_count

from stp_core.loop.eventually import eventually
from plenum.common.types import HA
from stp_core.common.log import getlogger
from plenum.test.helper import sendReqsToNodesAndVerifySuffReplies, \
    check_last_ordered_3pc
from plenum.test.node_catchup.helper import waitNodeDataEquality, \
    check_ledger_state
from plenum.test.pool_transactions.helper import \
    disconnect_node_and_ensure_disconnected
from plenum.test.test_ledger_manager import TestLedgerManager
from plenum.test.test_node import checkNodesConnected, TestNode
from plenum.test import waits

# Do not remove the next import
from plenum.test.node_catchup.conftest import whitelist

logger = getlogger()
txnCount = 5


def testNewNodeCatchup(newNodeCaughtUp):
    """
    A new node that joins after some transactions are done should eventually get
    those transactions.
    TODO: Test correct statuses are exchanged
    TODO: Test correct consistency proofs are generated
    :return:
    """
    pass


def testPoolLegerCatchupBeforeDomainLedgerCatchup(txnPoolNodeSet,
                                                  newNodeCaughtUp):
    """
    For new node, this should be the sequence of events:
     1. Pool ledger starts catching up.
     2. Pool ledger completes catching up.
     3. Domain ledger starts catching up
     4. Domain ledger completes catching up
    Every node's pool ledger starts catching up before it
    """
    newNode = newNodeCaughtUp
    starts = newNode.ledgerManager.spylog.getAll(
        TestLedgerManager.startCatchUpProcess.__name__)
    completes = newNode.ledgerManager.spylog.getAll(
        TestLedgerManager.catchupCompleted.__name__)
    startTimes = {}
    completionTimes = {}
    for start in starts:
        startTimes[start.params.get('ledgerId')] = start.endtime
    for comp in completes:
        completionTimes[comp.params.get('ledgerId')] = comp.endtime
    assert startTimes[0] < completionTimes[0] < \
           startTimes[1] < completionTimes[1]


@pytest.mark.skip(reason="SOV-554. "
                         "Test implementation pending, although bug fixed")
def testDelayedLedgerStatusNotChangingState():
    """
    Scenario: When a domain `LedgerStatus` arrives when the node is in
    `participating` mode, the mode should not change to `discovered` if found
    the arriving `LedgerStatus` to be ok.
    """
    raise NotImplementedError


# TODO: This test passes but it is observed that PREPAREs are not received at
# newly added node. If the stop and start steps are omitted then PREPAREs are
# received. Conclusion is that due to node restart, RAET is losing messages
# but its weird since prepares and commits are received which are sent before
# and after prepares, respectively. Here is the pivotal link
# https://www.pivotaltracker.com/story/show/127897273
def testNodeCatchupAfterRestart(newNodeCaughtUp, txnPoolNodeSet, tconf,
                                nodeSetWithNodeAddedAfterSomeTxns,
                                tdirWithPoolTxns, allPluginsPath):
    """
    A node that restarts after some transactions should eventually get the
    transactions which happened while it was down
    :return:
    """
    looper, newNode, client, wallet, _, _ = nodeSetWithNodeAddedAfterSomeTxns
    logger.debug("Stopping node {} with pool ledger size {}".
                 format(newNode, newNode.poolManager.txnSeqNo))
    disconnect_node_and_ensure_disconnected(looper, txnPoolNodeSet, newNode)
    looper.removeProdable(newNode)
    # for n in txnPoolNodeSet[:4]:
    #     for r in n.nodestack.remotes.values():
    #         if r.name == newNode.name:
    #             r.removeStaleCorrespondents()
    # looper.run(eventually(checkNodeDisconnectedFrom, newNode.name,
    #                       txnPoolNodeSet[:4], retryWait=1, timeout=5))
    # TODO: Check if the node has really stopped processing requests?
    logger.debug("Sending requests")
    more_requests = 5
    sendReqsToNodesAndVerifySuffReplies(looper, wallet, client, more_requests)
    logger.debug("Starting the stopped node, {}".format(newNode))
    nodeHa, nodeCHa = HA(*newNode.nodestack.ha), HA(*newNode.clientstack.ha)
    newNode = TestNode(newNode.name, basedirpath=tdirWithPoolTxns, config=tconf,
                       ha=nodeHa, cliha=nodeCHa, pluginPaths=allPluginsPath)
    looper.add(newNode)
    txnPoolNodeSet[-1] = newNode

    # Delay catchup reply processing so LedgerState does not change
    delay_catchup_reply = 5
    newNode.nodeIbStasher.delay(cr_delay(delay_catchup_reply))
    looper.run(checkNodesConnected(txnPoolNodeSet))

    # Make sure ledger starts syncing (sufficient consistency proofs received)
    looper.run(eventually(check_ledger_state, newNode, DOMAIN_LEDGER_ID,
                          LedgerState.syncing, retryWait=.5, timeout=5))

    confused_node = txnPoolNodeSet[0]
    new_node_ledger = newNode.ledgerManager.ledgerRegistry[DOMAIN_LEDGER_ID]
    cp = new_node_ledger.catchUpTill
    start, end = cp.seqNoStart, cp.seqNoEnd
    cons_proof = confused_node.ledgerManager._buildConsistencyProof(
        DOMAIN_LEDGER_ID, start, end)

    bad_send_time = None

    def chk():
        nonlocal bad_send_time
        entries = newNode.ledgerManager.spylog.getAll(
            newNode.ledgerManager.canProcessConsistencyProof.__name__)
        for entry in entries:
            # `canProcessConsistencyProof` should return False after `syncing_time`
            if entry.result == False and entry.starttime > bad_send_time:
                return
        assert False

    def send_and_chk(ledger_state):
        nonlocal bad_send_time, cons_proof
        bad_send_time = perf_counter()
        confused_node.ledgerManager.sendTo(cons_proof, newNode.name)
        # Check that the ConsistencyProof messages rejected
        looper.run(eventually(chk, retryWait=.5, timeout=5))
        check_ledger_state(newNode, DOMAIN_LEDGER_ID, ledger_state)

    send_and_chk(LedgerState.syncing)

    # Not accurate timeout but a conservative one
    timeout = waits.expectedPoolGetReadyTimeout(len(txnPoolNodeSet)) + \
              2*delay_catchup_reply
    waitNodeDataEquality(looper, newNode, *txnPoolNodeSet[:-1],
                         customTimeout=timeout)
    assert new_node_ledger.num_txns_caught_up == more_requests
    send_and_chk(LedgerState.synced)


def testNodeCatchupAfterRestart1(newNodeCaughtUp, txnPoolNodeSet, tconf,
                                nodeSetWithNodeAddedAfterSomeTxns,
                                tdirWithPoolTxns, allPluginsPath):
    """
    A node restarts but no transactions have happened while it was down.
    It would then use the `LedgerStatus` to catchup
    """
    looper, new_node, client, wallet, _, _ = nodeSetWithNodeAddedAfterSomeTxns

    logger.debug("Stopping node {} with pool ledger size {}".
                 format(new_node, new_node.poolManager.txnSeqNo))
    disconnect_node_and_ensure_disconnected(looper, txnPoolNodeSet, new_node)
    looper.removeProdable(name=new_node.name)

    logger.debug("Starting the stopped node, {}".format(new_node))
    nodeHa, nodeCHa = HA(*new_node.nodestack.ha), HA(*new_node.clientstack.ha)
    new_node = TestNode(new_node.name, basedirpath=tdirWithPoolTxns, config=tconf,
                       ha=nodeHa, cliha=nodeCHa, pluginPaths=allPluginsPath)
    looper.add(new_node)
    txnPoolNodeSet[-1] = new_node
    looper.run(checkNodesConnected(txnPoolNodeSet))

    def chk():
        for node in txnPoolNodeSet[:-1]:
            check_last_ordered_3pc(new_node, node)

    looper.run(eventually(chk, retryWait=1))

    sendReqsToNodesAndVerifySuffReplies(looper, wallet, client, 5)
    waitNodeDataEquality(looper, new_node, *txnPoolNodeSet[:-1])
    # Did not receive any consistency proofs
    assert get_count(new_node.ledgerManager,
                     new_node.ledgerManager.processConsistencyProof) == 0
