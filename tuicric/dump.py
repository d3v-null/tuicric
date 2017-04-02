"""
Tools for dumping SysEx data.
"""
# pylint: disable=missing-super-argument, redefined-builtin
from __future__ import absolute_import, division, print_function

import io
import binascii
import logging
import re
import argparse
from builtins import (bytes, str, super)
from tabulate import tabulate

def make_id(string):
    """Make an id out of a string."""

    response = string.lower()
    response = re.sub(r'\W', '', response)
    return '%s' % response

class SysexInfo(list):
    """List of `SysexInfoSection`s which contains info about a SysEx message."""

    def to_gv(self):
        section_components = [section.to_gv() for section in self]
        connection_components = [
            'handle_oscillator1:out -> oscillator1level:in',
            'handle_oscillator2:out -> oscillator2level:in'
        ]
        connection_components.append('')
        return "digraph {\n\t" \
            + "\n\t".join(section_components) \
            + "\n\t" \
            + ";\n\t".join(connection_components) \
            + "}"

class SysexInfoSection(list):
    """List of `SysexInfoParam`s which contains info about part of a Sysex message."""

    def __init__(self, name='', params=None):
        if params is None:
            params = []
        self.name = name
        super().__init__(params)

    @property
    def gvid(self):
        """ID for graphviz."""

        return 'cluster_%s' % make_id(self.name)

    @property
    def gv_components(self):
        """Graphviz components for section."""
        response = [
            "handle_%s [style=bold,shape=record,label=\"<in>|%s|<out>\"]" % \
                (make_id(self.name), self.name)
        ]
        response += [param.to_gv() for param in self]
        return response

    def to_gv(self):
        return "subgraph %s {\n\t\t" % self.gvid \
                + ";\n\t\t".join(self.gv_components) + ";\n\t}"


class SysexInfoSectionOscillator(SysexInfoSection):
    """List of `SysexInfoParam`s specific to a Circuit Oscillator."""

    def __init__(self, name='', offset=0x00):
        params = [
            SysexInfoParamChoiceOscWave(
                offset + 0x00, name + ' Wave', default=2
            ),
            SysexInfoParamMap(
                offset + 0x01, name + ' Wave Interpolate'
            ),
            SysexInfoParamMap(
                offset + 0x02, name + ' Pulse Withdraw Index',
                map_min=-64, map_max=64, default=127, fmt_str='%s'
            ),
            SysexInfoParamMap(
                offset + 0x03, name + ' Virtual Sync Depth',
            ),
            SysexInfoParamMap(
                offset + 0x03, name + ' Density',
            ),
            SysexInfoParamMap(
                offset + 0x03, name + ' Density Detune',
            ),
            SysexInfoParamMap(
                offset + 0x02, name + ' Semitones',
                map_min=-64, map_max=64, default=64, fmt_str='%+d semitones'
            ),
            SysexInfoParamMap(
                offset + 0x02, name + ' Cents',
                map_min=-100, map_max=100, default=64, fmt_str='%+d cents'
            ),
        ]
        super().__init__(name, params)

class SysexInfoSectionMixer(SysexInfoSection):
    """List of `SysexInfoParam`s specific to a Circuit Mixer."""

    def __init__(self, name='', offset=0x00):
        params = [
            SysexInfoParamMap(
                offset + 0x00, 'Oscillator 1 Level', default=127
            ),
            SysexInfoParamMap(
                offset + 0x01, 'Oscillator 2 Level', default=0
            ),
            SysexInfoParamMap(
                offset + 0x02, 'Ring Mod Level'
            ),
            SysexInfoParamMap(
                offset + 0x03, 'Noise Level'
            ),
            SysexInfoParamMap( # TODO: Defaults seem weird here
                offset + 0x04, 'Pre FX Level',
                map_min=-12.0, map_max=18.0, default=64, fmt_str='%.2fdB'
            ),
            SysexInfoParamMap(
                offset + 0x05, 'Post FX Level',
                map_min=-12.0, map_max=18.0, default=64, fmt_str='%.2fdB'
            ),
        ]
        super().__init__(name, params)

    @property
    def gv_components(self):
        response = super().gv_components
        response += [
            'oscillator1level:out -> ringmodlevel:in',
            'oscillator2level:out -> ringmodlevel:in',
            'ringmodlevel:out -> prefxlevel:in'
            # 'oscillator1level:out -> prefxlevel:in'
            # 'oscillator2level:out -> prefxlevel:in'
            # 'noiselevel:out -> prefxlevel:in'
        ]
        return response

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
        self.raw = None

    def format(self, raw):
        """Format the raw value."""
        assert \
            self.range_min <= raw and raw <= self.range_max, \
            "raw (%s) should be within range (%s..%s)" % (
                repr(raw), repr(self.range_min), repr(self.range_max)
            )
        return raw

    @property
    def value(self):
        raw = self.default
        if self.raw is not None:
            raw = self.raw
        return self.format(raw)

    @property
    def gvid(self):
        """ID for graphviz."""

        return make_id(self.name)

    @property
    def label(self):
        return "{<mod>|<in>}|{%s|%s}|<out>" % (self.name, self.value)

    def to_gv(self):
        return "%s [" % self.gvid \
            + "shape=record," \
            + "label=\"%s\"" % self.label \
            + "]"


class SysexInfoParamChoice(SysexInfoParam):
    """Contains information about a single multi-choice param within a sysex message."""

    def __init__(self, offset, name='', choices=None, *args, **kwargs):
        assert \
            len(choices) >= 1, \
            "Should be at least one choice"

        self.choices = choices

        kwargs['range_max'] = kwargs.get('range_min', 0) + len(choices) - 1
        super().__init__(offset, name, *args, **kwargs)

    def format(self, raw):
        raw = super().format(raw)
        assert \
            raw < len(self.choices), \
            "raw %d should be in index of choices: %d" % (raw, len(self.choices))
        return self.choices[raw]

class SysexInfoParamChoiceOscWave(SysexInfoParamChoice):
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

class SysexInfoParamChoiceLFOWave(SysexInfoParamChoice):
    """Contains information about a single wave select param within a sysex message."""

    def __init__(self, offset, name='', *args, **kwargs):
        choices = ['sine', 'triangle', 'sawtooth', 'square', 'random S/H',
                   'time S/H', 'piano envelope', 'sequence 1', 'sequence 2',
                   'sequence 3', 'sequence 4', 'sequence 5', 'sequence 6',
                   'sequence 7', 'alternative 1', 'alternative 2',
                   'alternative 3', 'alternative 4', 'alternative 5',
                   'alternative 6', 'alternative 7', 'alternative 8',
                   'chromatic', 'chromatic 16', 'major', 'major 7',
                   'minor 7', 'minor arp 1', 'minor arp 2', 'diminished',
                   'dec minor', 'minor 3rd', 'pedal', '4ths', '4ths x 12',
                   '1625 Maj', '1625 Min', '2511']
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
    SysexInfoSectionOscillator(
        name='Oscillator 1',
        offset=0x2D
    ),
    SysexInfoSectionOscillator(
        name='Oscillator 2',
        offset=0x36
    ),
    SysexInfoSectionMixer(
        name='Mixer',
        offset=0x3F
    )

])
#
# class SysexInfoParamCC(SysexInfoParam):
#     """A class containing information about a single Control Change param."""
#
# class SysexInfoParamNRPN(SysexInfoParam):
#     """A class containing information about a single Non-Registered param."""

def dump_sysex_patch_gv(sysex):
    """Create a graphviz representation of the SysEx patch bytestring."""

    logging.info("dumping sysex:\n%s", binascii.b2a_qp(sysex))
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
        group_table = []
        for param in info_section:
            raw = ord(sysex[param.offset])
            param.raw = raw
            group_table.append(['', param.name, raw, param.value])

        logging.info(
            "%s\n%s",
            info_section.name,
            tabulate(group_table, headers=['', 'Parameter', 'raw', 'value'])
        )

    return PATCH_INFO.to_gv()

def main():
    """Main function for duping sysex."""
    logging.basicConfig(level=logging.INFO)

    argparser = argparse.ArgumentParser()
    argparser.add_argument('--sysex-file')
    argparser.add_argument('--gv-file')
    args = argparser.parse_args()

    if args:
        gv_contents = ""
        with io.FileIO(args.sysex_file, 'r') as raw_sysex:
            gv_contents = dump_sysex_patch_gv(raw_sysex.readall())
        if gv_contents:
            with open(args.gv_file, 'w+') as gv_file:
                gv_file.write(gv_contents)

if __name__ == '__main__':
    main()
