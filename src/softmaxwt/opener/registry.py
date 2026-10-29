from softmaxwt.opener import cmux, inplace, noop, zellij
from softmaxwt.opener.common import Opener, OpenerName

_OPENERS: dict[OpenerName, Opener] = {
    OpenerName.inplace: inplace,
    OpenerName.cmux: cmux,
    OpenerName.zellij: zellij,
    OpenerName.noop: noop,
}


def get_opener(name: OpenerName) -> Opener:
    return _OPENERS[name]


def all_openers() -> list[Opener]:
    return list(_OPENERS.values())
