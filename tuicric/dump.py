"""
Tools for dumping SysEx data.
"""
# pylint: disable=missing-super-argument, redefined-builtin
from __future__ import absolute_import, division, print_function

import io
import argparse
import binascii
import logging
from builtins import (bytes, str, open, super)
from tabulate import tabulate

class SysexInfo(list):
    """List of `SysexInfoSection`s which contains info about a SysEx message."""

class SysexInfoSection(list):
    """List of `SysexInfoParam`s which contains info about part of a Sysex message."""

    def __init__(self, name=None, params=None):
        if not name:
            name = ''
        if params is None:
            params = []
        self.name = name
        super().__init__(params)

class SysexInfoParam(object):
    """Contains information about a single param within a sysex message."""

    def __init__(self, offset, name='', range_min=0, range_max=127, default=0):
        assert \
            range_min <= range_max, \
            "sanity check: range min <= range max"
        assert \
            range_min <= default and default <= range_max, \
            "sanity check: default (%d) within range (%d..%d)" % (
                default, range_min, range_max
            )
        self.offset = offset
        self.name = name
        self.range_min = range_min
        self.range_max = range_max
        self.default = default

    def format(self, raw):
        """Format the raw value."""
        assert \
            raw in range(self.range_min, self.range_max), \
            "raw (%s) should be within range (%s..%s)" % (
                repr(raw), repr(self.range_min), repr(self.range_max)
            )
        return raw


class SysexInfoParamChoice(SysexInfoParam):
    """Contains information about a single multi-choice param within a sysex message."""

    def __init__(self, offset, name='', choices=None, *args, **kwargs):
        assert \
            len(choices) >= 1, \
            "Should be at least one choice"

        self.choices = choices

        kwargs['range_max'] = kwargs.get('range_min', 0) + len(choices)
        super().__init__(offset, name, *args, **kwargs)

    def format(self, raw):
        raw = super().format(raw)
        return self.choices[raw]

class SysexInfoParamChoiceWave(SysexInfoParamChoice):
    """Contains information about a single wave select param within a sysex message."""

    def __init__(self, offset, name='', *args, **kwargs):
        choices = ['sine', 'triangle', 'sawtooth', 'saw 9:1 PW', 'saw 8:2 PW',
                   'saw 7:3 PW', 'saw 6:4 PW', 'saw 5:5 PW', 'saw 4:6 PW',
                   'saw 3:7 PW', 'saw 2:8 PW', 'saw 1:9 PW', 'pulse width',
                   'square', 'sine table', 'analogue pulse', 'analogue sync',
                   'triange-saw blend', 'digital nasty 1', 'digital nasty 2',
                   'digital saw-square', 'digital vocal 1', 'digital vocal 2',
                   'digital vocal 3', 'digital vocal 4', 'digital vocal 5',
                   'digital vocal 6', 'random collection 1',
                   'random collection 2', 'random collection 3']
        super().__init__(offset, name, choices, *args, **kwargs)

class SysexInfoParamMap(SysexInfoParam):
    """Contains information about a single mapped param within a sysex message."""

    def __init__(self, offset, name='', map_min=0, map_max=100, fmt_str='%s%%', *args, **kwargs):
        assert \
            isinstance(map_min, type(map_max)), \
            "types of map_min and map_max should be the same, intead: %s, %s" % (
                type(map_min), type(map_max)
            )
        self.map_min = map_min
        self.map_max = map_max
        self.fmt_str = fmt_str
        super().__init__(offset, name, *args, **kwargs)

    def format(self, raw):
        raw = super().format(raw)
        mapped = (raw - self.range_min) * (self.map_max - self.map_min) \
                / (self.range_max - self.range_min) + self.map_min
        mapped_type = type(self.map_min)
        return self.fmt_str % mapped_type(mapped)


PATCH_LEN = 350
PATCH_HEADER = binascii.a2b_hex('F0002029')
PATCH_INFO = SysexInfo([
    SysexInfoSection(
        name='Voice',
        params=[
            SysexInfoParamChoice(
                0x29, 'Polyphony Mode', ['Mono', 'MonoAG', 'Poly'], default=2
            ),
            SysexInfoParamMap(
                0x2A, 'Portamento Rate'
            ),
            SysexInfoParamMap(
                0x2B, 'Pre-Glide',
                range_min=52, range_max=76, map_min=-12, map_max=12, default=64,
                fmt_str='%+d semitones'
            ),
            SysexInfoParamMap(
                0x2C, 'Keyboard Octave',
                range_min=58, range_max=69, map_min=-6, map_max=5, default=64,
                fmt_str='%+d octaves'
            )
        ]
    ),
    SysexInfoSection(
        name='Oscillator',
        params=[
            SysexInfoParamChoiceWave(
                0x2D, 'Osc 1 Wave', default=2
            ),
            SysexInfoParamMap(
                0x2E, 'Osc 1 Wave Interpolate',
            )
        ]
    )
])
#
# class SysexInfoParamCC(SysexInfoParam):
#     """A class containing information about a single Control Change param."""
#
# class SysexInfoParamNRPN(SysexInfoParam):
#     """A class containing information about a single Non-Registered param."""

def dump_sysex_patch(sysex):
    """Create a string representation of the SysEx patch bytestring."""

    logging.info("dumping sysex:\n%s" % binascii.b2a_qp(sysex))
    assert \
        isinstance(sysex, bytes), \
        "sysex must be a bytestring"

    assert \
        sysex.startswith(PATCH_HEADER), \
        "sysex should start with valid header: \n%s \ninstead: \n%s... " % (
            binascii.b2a_hex(PATCH_HEADER),
            binascii.b2a_hex(sysex[:len(PATCH_HEADER)])
        )

    assert \
        len(sysex) == PATCH_LEN, \
        "Sysex should be exactly %d characters long, instead %d" % (
            PATCH_LEN,
            len(sysex)
        )

    for info_section in PATCH_INFO:
        print(info_section.name)
        group_table = []
        for param in info_section:
            raw = ord(sysex[param.offset])
            group_table.append(['', param.name, raw, param.format(raw)])
        print(tabulate(group_table, headers=['', 'Parameter', 'raw', 'value']))

def main():
    """Main function for duping sysex."""
    logging.basicConfig(level=logging.INFO)

    argparser = argparse.ArgumentParser()
    argparser.add_argument('--sysex-file')
    args = argparser.parse_args()

    if args:
        with io.FileIO(args.sysex_file, 'r') as raw_sysex:
            dump_sysex_patch(raw_sysex.readall())

if __name__ == '__main__':
    main()
