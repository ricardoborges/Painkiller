"""Symmetric encryption for the secrets kept in the settings table."""

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

#: Prefixo que marca um valor cifrado; o resto é o token Fernet.
PREFIX = "enc:v1:"


class SecretBox:
    """Fernet keyed by a passphrase (the installation's secret key).

    Uma passphrase diferente torna os valores antigos ilegíveis: `open` devolve
    None e quem chamou trata o campo como não configurado.
    """

    def __init__(self, passphrase: str):
        digest = hashlib.sha256(b"painkiller-settings:" + passphrase.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def seal(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        return PREFIX + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def open(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        if not value.startswith(PREFIX):
            return value
        try:
            return self._fernet.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            logger.warning("Segredo salvo não pôde ser decifrado (a chave da instalação mudou?).")
            return None
