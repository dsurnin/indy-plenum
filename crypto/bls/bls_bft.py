from abc import ABCMeta, abstractmethod
from typing import Sequence

from crypto.bls.bls_crypto import BlsCrypto
from crypto.bls.bls_key_register import BlsKeyRegister
from plenum.common.messages.node_messages import PrePrepare, Prepare, Commit
from plenum.server.quorums import Quorums
from typing import Optional


class BlsBft(metaclass=ABCMeta):
    def __init__(self,
                 bls_crypto: BlsCrypto,
                 bls_key_register: BlsKeyRegister,
                 node_id):
        self.bls_crypto = bls_crypto
        self.bls_key_register = bls_key_register
        self.node_id = node_id

    @abstractmethod
    def validate_pre_prepare(self, pre_prepare: PrePrepare, sender, stable_state_root):
        pass

    @abstractmethod
    def validate_prepare(self, prepare: Prepare, sender):
        pass

    @abstractmethod
    def validate_commit(self, commit: Commit, sender, state_root):
        pass

    @abstractmethod
    def sign_state(self, state_root: str) -> str:
        pass

    @abstractmethod
    def calculate_multi_sig(self,
                            key_3PC,
                            quorums: Quorums) -> Optional[tuple]:
        """
        Creates multi-signature

        :param key_3PC:
        :param quorums:
        :return: tuple of participants and signature itself
        """
        # TODO: replace tuple by class for signature
        pass

    @abstractmethod
    def validate_multi_sig(self, multi_sig: str, participants, state_root):
        pass

    @abstractmethod
    def save_multi_sig_local(self,
                             multi_sig: str,
                             participants: list,
                             state_root,
                             key_3PC):
        """
        Save multi-sig as calculated by the node independently

        :param multi_sig:
        """

    @abstractmethod
    def save_multi_sig_shared(self, pre_prepare: PrePrepare, key_3PC):
        """
        Save multi-sig as received from the Primary

        :param multi_sig:
        """

    @abstractmethod
    def gc(self, key_3PC):
        """
        Do some cleaning if needed

        :param key_3PC:
        """
        pass


class BlsValidationError(Exception):
    """
    BLS signature validation error
    """