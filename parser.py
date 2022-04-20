import portion as I
from version import Version
from lark import Lark, InlineTransformer


def parse_or_empty(parser, text, verbose=False):
    try:
        return parser.parse(text)
    except Exception as e:
        if verbose:
            print('E:', text, str(e))
        return I.empty()


def patch_interval(version):
    return I.closedopen(
        version,
        Version(version.major, version.minor + 1, 0)
    )


def minor_interval(version):
    return I.closedopen(
        version,
        Version(version.major + 1, 0, 0)
    )


def comparator_interval(op, version):
    if op == '=':
        return I.singleton(version)
    if op == '<':
        return I.closedopen(Version.FIRST, version)
    if op == '<=':
        return I.closed(Version.FIRST, version)
    if op == '>':
        return I.open(version, I.inf)
    if op == '>=':
        return I.closedopen(version, I.inf)
    if op == '!=':
        return I.closedopen(Version.FIRST, version) | I.openclosed(version, I.inf)


class SemVerParser(InlineTransformer):
    grammar = r"""
    constraints: [range_set]
    range_set  : range ( "||" range ) *
    range      : hyphen | simple ( " " simple ) *
    hyphen.1   : partial " - " partial
    simple     : primitive | partial | tilde | caret
    primitive  : [OP] partial
    OP         : "<=" | ">=" | ">" | "<" | "="
    partial    : ("v"|"V")? XR ( "." XR ( "." XR qualifier ? )? )?
    XR        : "x" | "X" | "*" | /0|[1-9]([0-9])*/
    tilde      : "~" partial
    caret      : "^" partial
    ?qualifier : ( "-" pre )? ( "+" build )?
    ?pre       : parts
    ?build     : parts
    ?parts     : part ( "." part ) *
    ?part      : /0|[1-9]([0-9])*/ | /[\-0-9A-Za-z]+/

    %import common.WS
    %ignore WS
    """

    def __init__(self):
        self._parser = Lark(self.grammar, start='constraints')

    def parse(self, text):
        return self.transform(self._parser.parse(text))

    def constraints(self, interval=None):
        return I.closed(Version.FIRST, I.inf) if interval is None else interval

    def range_set(self, *intervals):
        interval = I.empty()
        for other_interval in intervals:
            interval = interval | other_interval
        return interval

    def range(self, *intervals):
        interval = I.closedopen(Version.FIRST, I.inf)
        for other_interval in intervals:
            interval = interval & other_interval

        return interval

    def simple(self, interval_or_tuple):
        if isinstance(interval_or_tuple, I.Interval):
            return interval_or_tuple
        else:
            return self.primitive(interval_or_tuple)

    def tilde(self, version):
        major, minor, patch = version

        # Desugar *
        major = None if major == '*' else major
        minor = None if minor == '*' else minor
        patch = None if patch == '*' else patch

        if minor is None:
            # ~0 := >=0.0.0 <(0+1).0.0 := >=0.0.0 <1.0.0 (Same as 0.x)
            # ~1 := >=1.0.0 <(1+1).0.0 := >=1.0.0 <2.0.0 (Same as 1.x)
            return minor_interval(Version(major, 0, 0))
        elif patch is None:
            # ~0.2 := >=0.2.0 <0.(2+1).0 := >=0.2.0 <0.3.0 (Same as 0.2.x)
            # ~1.2 := >=1.2.0 <1.(2+1).0 := >=1.2.0 <1.3.0 (Same as 1.2.x)
            return patch_interval(Version(major, minor, 0))
        else:
            # ~0.2.3 := >=0.2.3 <0.(2+1).0 := >=0.2.3 <0.3.0
            # ~1.2.3 := >=1.2.3 <1.(2+1).0 := >=1.2.3 <1.3.0
            return patch_interval(Version(major, minor, patch))

    def caret(self, version):
        major, minor, patch = version

        # Desugar *
        major = None if major == '*' else major
        minor = None if minor == '*' else minor
        patch = None if patch == '*' else patch

        if major == 0:
            if minor is None:
                # ^0.x := >=0.0.0 <1.0.0
                return minor_interval(Version(0, 0, 0))
            elif patch is None:
                # ^0.0.x := >=0.0.0 <0.1.0
                # ^0.0 := >=0.0.0 <0.1.0
                # ^0.1.x := >=0.1.0 <0.2.0
                return patch_interval(Version(0, minor or 0, 0))
            else:
                if minor == 0:
                    # ^0.0.3 := >=0.0.3 <0.0.4
                    return I.closedopen(Version(0, 0, patch), Version(0, 0, patch + 1))
                else:
                    # ^0.2.3 := >=0.2.3 <0.3.0
                    return patch_interval(Version(0, minor, patch))
        else:
            # ^1.x := >=1.0.0 <2.0.0
            # ^1.2.x := >=1.2.0 <2.0.0
            # ^1.2.3 := >=1.2.3 <2.0.0
            return minor_interval(Version(major, minor or 0, patch or 0))

    def primitive(self, op, version=None):
        if version is None:
            version = op
            op = '='

        major, minor, patch = version
        # Desugar *
        major = None if major == '*' else major
        minor = None if minor == '*' else minor
        patch = None if patch == '*' else patch

        if major is None:
            return I.closedopen(Version.FIRST, I.inf)
        elif minor is None:
            return minor_interval(Version(major, 0, 0))
        elif patch is None:
            return patch_interval(Version(major, minor, 0))
        else:
            return comparator_interval(op, Version(major, minor, patch))

    def hyphen(self, left, right):
        lmajor, lminor, lpatch = left
        rmajor, rminor, rpatch = right

        lminor = 0 if lminor is None else lminor
        lpatch = 0 if lpatch is None else lpatch

        if rminor is None:
            # 1.0.0 - 2 := >=1.0.0 <3.0.0 because "2" becames "2.*.*"
            return I.closedopen(
                Version(lmajor, lminor, lpatch),
                Version(rmajor + 1, 0, 0)
            )
        elif rpatch is None:
            # 1.0.0 - 2.0 := >=1.0.0 <2.1 because "2.0" becames "2.0.*"
            return I.closedopen(
                Version(lmajor, lminor, lpatch),
                Version(rmajor, rminor + 1, 0)
            )
        else:
            # Inclusive
            return I.closed(Version(lmajor, lminor, lpatch), Version(rmajor, rminor, rpatch))

    def partial(self, major, minor=None, patch=None, misc=None):
        major = '*' if major in ['x', 'X', '*'] else major
        minor = '*' if minor in ['x', 'X', '*'] else minor
        patch = '*' if patch in ['x', 'X', '*'] else patch

        return tuple(
            int(x) if (x is not None and str.isdigit(x)) else x
            for x in (major, minor, patch)
        )
