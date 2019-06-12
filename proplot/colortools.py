#!/usr/bin/env python3
"""
Registers colormaps, color cycles, and color string names with
`register_cmaps`, `register_cycles`, and `register_colors`.
Defines tools for creating new colormaps and color cycles, i.e. `Colormap`
and `Cycle`. Defines helpful new `~matplotlib.colors.Normalize` and
`~matplotlib.colors.Colormap` classes.

See the :ref:`Color usage` section of "Getting Started" for details.
"""
# Potential bottleneck, loading all this stuff?  *No*. Try using @timer on
# register functions, turns out worst is colormap one at 0.1 seconds. Just happens
# to be a big package, takes a bit to compile to bytecode then import.
import os
import re
import json
import glob
from lxml import etree
from numbers import Number
import warnings
import numpy as np
import numpy.ma as ma
import matplotlib.colors as mcolors
import matplotlib.cm as mcm
import matplotlib as mpl
from . import utils, colormath
from .utils import _default, _counter, _timer, ic
rcParams = mpl.rcParams
# Data diretories
_delim = re.compile('[,\s]+')
_data_user = os.path.join(os.path.expanduser('~'), '.proplot')
_data_user_cmaps = os.path.join(_data_user, 'cmaps')
_data_user_cycles = os.path.join(_data_user, 'cycles')
_data_cmaps = os.path.join(os.path.dirname(__file__), 'cmaps') # or parent, but that makes pip install distribution hard
_data_cycles = os.path.join(os.path.dirname(__file__), 'cycles') # or parent, but that makes pip install distribution hard
_data_colors = os.path.join(os.path.dirname(__file__), 'colors') # or parent, but that makes pip install distribution hard
if not os.path.isdir(_data_user):
    os.mkdir(_data_user)
if not os.path.isdir(_data_user_cmaps):
    os.mkdir(_data_user_cmaps)
if not os.path.isdir(_data_user_cycles):
    os.mkdir(_data_user_cycles)

# Define some new palettes
# Note the default listed colormaps
_cycles_preset = {
    # Default matplotlib v2
    'default':      ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'],
    # Copied from stylesheets; stylesheets just add color themese from every possible tool, not already present as a colormap
    '538':          ['#008fd5', '#fc4f30', '#e5ae38', '#6d904f', '#8b8b8b', '#810f7c'],
    'ggplot':       ['#E24A33', '#348ABD', '#988ED5', '#777777', '#FBC15E', '#8EBA42', '#FFB5B8'],
    # The default seaborn ones (excluded deep/muted/bright because thought they were unappealing)
    'ColorBlind':   ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#F0E442', '#56B4E9'],
    'ColorBlind10': ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC", "#CA9161", "#FBAFE4", "#949494", "#ECE133", "#56B4E9"], # versions with more colors
    # From the website
    'FlatUI':       ["#3498db", "#e74c3c", "#95a5a6", "#34495e", "#2ecc71", "#9b59b6"],
    # Created with online tools; add to this
    # See: http://tools.medialab.sciences-po.fr/iwanthue/index.php
    'Warm':     [(51,92,103), (158,42,43), (255,243,176), (224,159,62), (84,11,14)],
    'Cool':     ["#6C464F", "#9E768F", "#9FA4C4", "#B3CDD1", "#C7F0BD"],
    'Sharp':    ["#007EA7", "#D81159", "#B3CDD1", "#FFBC42", "#0496FF"],
    'Hot':      ["#0D3B66", "#F95738", "#F4D35E", "#FAF0CA", "#EE964B"],
    'Contrast': ["#2B4162", "#FA9F42", "#E0E0E2", "#A21817", "#0B6E4F"],
    'Floral':   ["#23395B", "#D81E5B", "#FFFD98", "#B9E3C6", "#59C9A5"],
    }

# Color stuff
# Keep major color names, and combinations of those names
# TODO: Let user adjust color params? Maybe nobody cares.
_distinct_colors_space = 'hcl' # register colors distinct in this space?
_distinct_colors_threshold = 0.09 # bigger number equals fewer colors
_exceptions_names = (
    'sky blue', 'eggshell', 'sea blue', 'coral', 'tomato red', 'brick red', 'crimson',
    'red orange', 'yellow orange', 'yellow green', 'blue green',
    'blue violet', 'red violet',
    )
_bad_names = '(' + '|'.join(( # filter these out; let's try to be professional here...
    'shit', 'poo', 'pee', 'piss', 'puke', 'vomit', 'snot', 'booger',
    )) + ')'
_sanitize_names = ( # replace regex (first entry) with second entry
    ('/', ' '), ("'s", ''), ('grey', 'gray'),
    ('pinky', 'pink'), ('greeny', 'green'),
    ('bluey',  'blue'),
    ('robin egg', 'robins egg'),
    ('egg blue', 'egg'),
    (r'reddish', 'red'),
    (r'purplish', 'purple'),
    (r'bluish',  'blue'),
    (r'ish\b', ''),
    ('bluegray', 'blue gray'),
    ('grayblue', 'gray blue'),
    ('lightblue', 'light blue')
    )
_space_aliases = {
    'rgb':   'rgb',
    'hsv':   'hsv',
    'hpl':   'hpl',
    'hpluv': 'hpl',
    'hsl':   'hsl',
    'hsluv': 'hsl',
    'hcl':   'hcl',
    'lch':   'hcl',
    }
_channel_idxs = {
    'h': 0, 'hue': 0,
    's': 1, 'saturation': 1,
    'c': 1, 'chroma': 1,
    'l': 2, 'luminance': 2,
    'a': 3, 'alpha': 3,
    }

# Names of builtin colormaps
# NOTE: Has support for 'x' coordinates in first column.
# NOTE: For 'alpha' column, must use a .rgba filename
# TODO: Better way to save colormap files.
_cmap_categories = {
    # Your custom registered maps; this is a placeholder, meant to put these
    # maps at the top of the colormap table
    'User': [
        ],

    # We keep these ones
    'Matplotlib Originals': [
        'viridis', 'plasma', 'inferno', 'magma', 'twilight',
        ],

    # Assorted origin, but these belong together
    'Grayscale': [
        'Grays',
        'Mono',
        'GrayCycle',
        ],

    # CET isoluminant maps
    # See: https://peterkovesi.com/projects/colourmaps/
    # All the others have better options
    'Isoluminant': [
        'Iso1', 'Iso2', 'Iso3', 
        'Phase', # these actually from cmocean
        ],

    # Included ColorBrewer
    'ColorBrewer2.0 Sequential': [
        'Purples', 'Blues', 'Greens', 'Oranges', 'Reds',
        'YlOrBr', 'YlOrRd', 'OrRd', 'PuRd', 'RdPu', 'BuPu',
        'PuBu', 'PuBuGn', 'BuGn', 'GnBu', 'YlGnBu', 'YlGn'
        ],

    # Added diverging versions
    # See: http://soliton.vm.bytemark.co.uk/pub/cpt-city/jjg/polarity/index.html
    # Other JJ Green maps weren't that great
    # TODO: Add 'serated' maps? See: http://soliton.vm.bytemark.co.uk/pub/cpt-city/jjg/serrate/index.html
    # TODO: Add tool for cutting center out of ***any*** colormap by ending
    # with the _cut suffix or something?
    'ColorBrewer2.0 Diverging': [
        'Spectral', 'PiYG', 'PRGn', 'BrBG', 'PuOr', 'RdGY',
        'RdBu', 'RdYlBu', 'RdYlGn',
        ],

    # Custom maps
    'ProPlot Sequential': [
        'Marine',
        'Boreal',
        'Glacial',
        'Dusk',
        'Sunrise', 'Sunset', 'Fire',
        'Stellar'
        ],
        # 'Vibrant'], # empty at first, fill automatically
    'ProPlot Diverging': [
        'NegPos1', 'NegPos2', 'DryWet1', 'DryWet2',
        ],

    # Other
    # BlackBody2 is actually from Los Alamos, and a couple are from Kenneth's
    # website, but organization is better this way.
    'Misc': [
        'ColdHot',
        'bwr',
        'CoolWarm',
        'BuPi',
        'Viz',
        'MuBlue', 'MuRed', 'MuDry', 'MuWet',
        # 'Temp', # too un-uniform
        # 'BlackBody1', 'BlackBody2', 'BlackBody3', # 3rd one is actually sky theme from rafi
        # 'Star',
        # 'JMN', # James map; ugly, so deleted
        # 'CubeHelix', 'SatCubeHelix',
        # 'cividis',
        # 'Aurora', 'Space', # from PIEcrust; not uniform, so deleted
        # 'TemperatureJJG', # from JJG; ugly, so deleted
        # 'Kindlmann', 'ExtendedKindlmann',
        # 'Seismic', # note this one originally had hard boundaries/no interpolation
        # 'MutedBio', 'DarkBio', # from: ???, maybe SciVisColor
        # ],
    # Statistik
    # 'Statistik Stadt Zürich': [
    # 'Zürich Muted': [
        ],

    # cmOcean
    'cmOcean Sequential': [
        'Oxy', 'Thermal', 'Dense', 'Ice', 'Haline',
        'Deep', 'Algae', 'Tempo', 'Speed', 'Turbid', 'Solar', 'Matter',
        'Amp',
        ],
    'cmOcean Diverging': [
        'Balance', 'Curl', 'Delta'
        ],

    # SciVisColor
    # Culled these because some were ugly
    # Actually nevermind... point of these is to *combine* them, make
    # stacked colormaps that highlight different things.
    'SciVisColor Blues': [
        'Blue0', 'Blue1', 'Blue2', 'Blue3', 'Blue4', 'Blue5', 'Blue6', 'Blue7', 'Blue8', 'Blue9', 'Blue10', 'Blue11',
        ],
    'SciVisColor Greens': [
        'Green1', 'Green2', 'Green3', 'Green4', 'Green5', 'Green6', 'Green7', 'Green8',
        ],
    'SciVisColor Oranges': [
        'Orange1', 'Orange2', 'Orange3', 'Orange4', 'Orange5', 'Orange6', 'Orange7', 'Orange8',
        ],
    'SciVisColor Browns': [
        'Brown1', 'Brown2', 'Brown3', 'Brown4', 'Brown5', 'Brown6', 'Brown7', 'Brown8', 'Brown9',
        ],
    'SciVisColor Reds/Purples': [
        'RedPurple1', 'RedPurple2', 'RedPurple3', 'RedPurple4', 'RedPurple5', 'RedPurple6', 'RedPurple7', 'RedPurple8',
        ],

    # FabioCrameri
    # See: http://www.fabiocrameri.ch/colourmaps.php
    'Fabio Crameri Sequential': [
        'Acton', 'Buda', 'Lajolla',
        # 'Imola',
        'Bamako', 'Nuuk', 'Davos', 'Oslo', 'Devon', 'Tokyo',
        # 'Hawaii',
        'Batlow',
        'Turku', 'Bilbao', 'Lapaz',
        ],
    'Fabio Crameri Diverging': [
        'Roma', 'Broc', 'Cork',  'Vik', 'Oleron',
        # 'Lisbon', 'Tofino', 'Berlin',
        ],

    # Gross. These ones will be deleted.
    'Alt Sequential': [
        'binary', 'gist_yarg', 'gist_gray', 'gray', 'bone', 'pink',
        'spring', 'summer', 'autumn', 'winter', 'cool', 'Wistia',
        'multi', 'cividis',
        'afmhot', 'gist_heat', 'copper'
        ],
    'Alt Rainbow': [
        'multi', 'cividis'
        ],
    'Alt Diverging': [
        'coolwarm', 'bwr', 'seismic'
        ],
    'Miscellaneous Orig': [
        'flag', 'prism', 'ocean', 'gist_earth', 'terrain', 'gist_stern',
        'gnuplot', 'gnuplot2', 'CMRmap', 'brg', 'hsv', 'hot', 'rainbow',
        'gist_rainbow', 'jet', 'nipy_spectral', 'gist_ncar', 'cubehelix',
        ],

    # Kenneth Moreland
    # See: http://soliton.vm.bytemark.co.uk/pub/cpt-city/km/index.html
    # Soft coolwarm from: https://www.kennethmoreland.com/color-advice/
    # 'Kenneth Moreland': [
    #     'CoolWarm', 'MutedCoolWarm', 'SoftCoolWarm',
    #     'BlueTan', 'PurpleOrange', 'CyanMauve', 'BlueYellow', 'GreenRed',
    #     ],
    # 'Kenneth Moreland Sequential': [
    #     'BlackBody', 'Kindlmann', 'ExtendedKindlmann',
    #     ],

    # Los Alamos
    # See: https://datascience.lanl.gov/colormaps.html
    # Most of these have analogues in SciVisColor, previously added the few
    # unique ones to Miscellaneous category
    # 'Los Alamos Sequential': [
    #     'MutedRainbow', 'DarkRainbow', 'MutedBlue', 'DeepBlue', 'BrightBlue', 'BrightGreen', 'WarmGray',
    #     ],
    # 'Los Alamos Diverging': [
    #     'MutedBlueGreen', 'DeepBlueGreen', 'DeepBlueGreenAsym', 'DeepColdHot', 'DeepColdHotAsym', 'ExtendedCoolWarm'
    #     ],

    # Removed the "combo" maps (and ugly diverging ones) because these can
    # be built in proplot with the Colormap tool!
    # 'SciVisColor Diverging': [
    #     'Div1', 'Div2', 'Div3', 'Div4', 'Div5'
    #     ],
    # 'SciVisColor 3 Waves': [
    #     '3Wave1', '3Wave2', '3Wave3', '3Wave4', '3Wave5', '3Wave6', '3Wave7'
    #     ],
    # 'SciVisColor 4 Waves': [
    #     '4Wave1', '4Wave2', '4Wave3', '4Wave4', '4Wave5', '4Wave6', '4Wave7'
    #     ],
    # 'SciVisColor 5 Waves': [
    #     '5Wave1', '5Wave2', '5Wave3', '5Wave4', '5Wave5', '5Wave6'
    #     ],
    # 'SciVisColor Waves': [
    #     '3Wave1', '3Wave2', '3Wave3',
    #     '4Wave1', '4Wave2', '4Wave3',
    #     '5Wave1', '5Wave2', '5Wave3',
    #     ],
    # 'SciVisColor Inserts': [
    #     'Insert1', 'Insert2', 'Insert3', 'Insert4', 'Insert5', 'Insert6', 'Insert7', 'Insert8', 'Insert9', 'Insert10'
    #     ],
    # 'SciVisColor Thick Inserts': [
    #     'ThickInsert1', 'ThickInsert2', 'ThickInsert3', 'ThickInsert4', 'ThickInsert5'
    #     ],
    # 'SciVisColor Highlight': [
    #     'Highlight1', 'Highlight2', 'Highlight3', 'Highlight4', 'Highlight5',
    #     ],

    # Most of these were ugly, deleted them
    # 'SciVisColor Outlier': [
    #     'DivOutlier1', 'DivOutlier2', 'DivOutlier3', 'DivOutlier4',
    #     'Outlier1', 'Outlier2', 'Outlier3', 'Outlier4'
    #     ],

    # Duncan Agnew
    # See: http://soliton.vm.bytemark.co.uk/pub/cpt-city/dca/index.html
    # These are 1.0.5 through 1.4.0
    # 'Duncan Agnew': [
    #     'Alarm1', 'Alarm2', 'Alarm3', 'Alarm4', 'Alarm5', 'Alarm6', 'Alarm7'
    #     ],

    # Elevation and bathymetry
    # 'Geographic': [
    #     'Bath1', # from XKCD; see: http://soliton.vm.bytemark.co.uk/pub/cpt-city/xkcd/tn/xkcd-bath.png.index.html
    #     'Bath2', # from Tom Patterson; see: http://soliton.vm.bytemark.co.uk/pub/cpt-city/tp/index.html
    #     'Bath3', # from: http://soliton.vm.bytemark.co.uk/pub/cpt-city/ibcso/tn/ibcso-bath.png.index.html
    #     'Bath4', # ^^ same
    #     'Geography4-1', # mostly ocean
    #     'Geography5-4', # range must be -4000 to 5000
    #     'Geography1', # from ???
    #     'Geography2', # from: http://soliton.vm.bytemark.co.uk/pub/cpt-city/ngdc/tn/ETOPO1.png.index.html
    #     'Geography3', # from: http://soliton.vm.bytemark.co.uk/pub/cpt-city/mby/tn/mby.png.index.html
    #     ],
    }
# Categories to ignore/*delete* from dictionary because they suck donkey balls
_cmap_categories_delete = ['Alt Diverging', 'Alt Sequential', 'Alt Rainbow', 'Miscellaneous Orig']

# Slice indices that split up segments of names
# WARNING: Must add to this list manually! Not worth trying to generalize.
# List of string cmap names, and the indices where they can be broken into parts
_cmap_parts = {
    # Diverging colorbrewer
    'piyg':         (None, 2, None),
    'prgn':         (None, 1, 2, None), # purple red green
    'brbg':         (None, 2, 3, None), # brown blue green
    'puor':         (None, 2, None),
    'rdgy':         (None, 2, None),
    'rdbu':         (None, 2, None),
    'rdylbu':       (None, 2, 4, None),
    'rdylgn':       (None, 2, 4, None),
    # Other diverging
    'bwr':          (None, 1, 2, None),
    'coldhot':      (None, 4, None),
    'negpos':       (None, 3, None),
    'drywet':       (None, 3, None),
    }
# Tuple pairs of mirror image cmap names
_cmap_mirrors = [
    (name, ''.join(reversed([name[slice(*idxs[i:i+2])] for i in range(len(idxs)-1)])),)
    for name,idxs in _cmap_parts.items()
    ]

#------------------------------------------------------------------------------#
# Special classes
#------------------------------------------------------------------------------#
# Class for flexible color names. Explanation:
# 1. Matplotlib 'color' arguments are passed to to_rgba, which tries
#    to read directly from cache and if that fails, tries to sanitize input.
#    The sanitization raises error when encounters (colormap, idx) tuple. So
#    we need to override the *cache* instead of color dictionary itself!
# 2. Builtin to_rgb tries to get cached colors as dict[name, alpha],
#    resulting in key as (colorname, alpha) or ((R,G,B), alpha) tuple. Impossible
#    to differentiate this from (cmapname, index) usage! Must do try except lookup
#    into colormap dictionary every time. Don't want to do this for actual
#    color dict for sake of speed, so we only wrap *cache* lookup. Also we try
#    to avoid cmap lookup attempt whenever possible with if statements.
class ColorCacheDict(dict): # cannot be ColorDict because sphinx has issues, conflicts with colordict variable!
    """Special dictionary that lets user draw single color tuples from
    arbitrary colormaps or color cycles."""
    def __getitem__(self, key):
        """
        Either samples the color from a colormap or color cycle,
        or calls the parent getitem to look up the color name.

        For a **smooth colormap**, usage is e.g.
        ``color=('Blues', 0.8)`` -- the number should be between 0 and 1, and
        indicates where to draw the color from the smooth colormap. For a
        "listed" colormap, i.e. a **color cycle**, usage is e.g.
        ``color=('colorblind', 2)``. The number indicates the index in the
        list of discrete colors.

        These examples work with any matplotlib command that accepts
        a ``color`` keyword arg.
        """
        # Pull out alpha
        # WARNING: Possibly fragile? Does this hidden behavior ever change?
        if np.iterable(key) and len(key)==2:
            key, alpha = key
        if np.iterable(key) and len(key)==2 and \
            isinstance(key[1], Number) and isinstance(key[0], str): # i.e. is not None; this is *very common*, so avoids lots of unnecessary lookups!
            try:
                cmap = mcm.cmap_d[key[0]]
            except (TypeError, KeyError):
                pass
            else:
                if isinstance(cmap, mcolors.ListedColormap):
                    rgb = tuple(cmap.colors[key[1]]) # draw color from the list of colors, using index
                else:
                    rgb = tuple(cmap(key[1])) # interpolate color from colormap, using key in range 0-1
                if len(rgb)==3:
                    rgb = (*rgb, 1)
                return rgb
        return super().__getitem__((key, alpha))
# Wraps the cache
class _ColorMappingOverride(mcolors._ColorMapping):
    def __init__(self, mapping):
        """Wraps the cache."""
        super().__init__(mapping)
        self.cache = ColorCacheDict({})
# Override default color name dictionary
if not isinstance(mcolors._colors_full_map, _ColorMappingOverride):
    mcolors._colors_full_map = _ColorMappingOverride(mcolors._colors_full_map)

# List of colors with 'name' attribute
class ColorCycle(list):
    def __repr__(self):
        """Wraps the string representation."""
        return 'ColorCycle(' + super().__repr__() + ')'

    def __getitem__(self, key):
        """Cyclic getitem."""
        return super().__getitem__(key % len(self))

    def __init__(self, list_, name):
        """Simply stores a list of colors, and adds a `name` attribute
        corresponding to the registered name."""
        super().__init__(list_)
        self.name = name

# Flexible colormap identification
class CmapDict(dict):
    def __init__(self, kwargs):
        """
        Flexible, case-insensitive colormap identification. Replaces the
        `matplotlib.cm.cmap_d` dictionary that stores registered colormaps.

        Behaves like a dictionary, with three new features:

        1. Names are case insensitive: ``'Blues'``, ``'blues'``, and ``'bLuEs'``
           are all valid names for the "Blues" colormap.
        2. "Reversed" colormaps are not stored directly: Requesting e.g.
           ``'Blues_r'`` will just look up ``'Blues'``, then return the result
           of the `~matplotlib.colors.Colormap.reversed` method.
        3. Diverging colormap names can be referenced by their "inverse" name.
           For example, ``'BuRd'`` is equivalent to ``'RdBu_r'``, as are
           ``'BuYlRd'`` and ``'RdYlBu_r'``.
        """
        kwargs_filtered = {}
        for key,value in kwargs.items():
            if not isinstance(key, str):
                raise KeyError(f'Invalid key {key}. Must be string.')
            if key[-2:] != '_r': # don't need to store these!
                kwargs_filtered[key.lower()] = value
        super().__init__(kwargs_filtered)

    def _sanitize_key(self, key):
        """Sanitizes key name."""
        # Try retrieving
        if not isinstance(key, str):
            raise ValueError(f'Invalid key {key}. Must be string.')
        key = key.lower()
        reverse = False
        if key[-2:] == '_r':
            key = key[:-2]
            reverse = True
        # Attempt to get 'mirror' key, maybe that's the one
        # stored in colormap dict
        if not super().__contains__(key):
            key_mirror = key
            for mirror in _cmap_mirrors:
                try:
                    idx = mirror.index(key)
                    key_mirror = mirror[1 - idx]
                except ValueError:
                    continue
            if super().__contains__(key_mirror):
                reverse = (not reverse)
                key = key_mirror
        # Return 'sanitized' key. Not necessarily in dictionary! Error
        # will be raised further down the line if so.
        if reverse:
            key = key + '_r'
        return key

    def _getitem(self, key):
        """Get value, but skip key sanitization."""
        reverse = False
        if key[-2:] == '_r':
            key = key[:-2]
            reverse = True
        value = super().__getitem__(key) # may raise keyerror
        if reverse:
            try:
                value = value.reversed()
            except AttributeError:
                raise KeyError(f'Dictionary value in {key} must have reversed() method.')
        return value

    def __getitem__(self, key):
        """Sanitizes key, then queries dictionary."""
        key = self._sanitize_key(key)
        return self._getitem(key)

    def __setitem__(self, key, item):
        """Assigns lowercase."""
        if not isinstance(key, str):
            raise KeyError(f'Invalid key {key}. Must be string.')
        return super().__setitem__(key.lower(), item)

    def __contains__(self, item):
        """The 'in' behavior."""
        try:
            self.__getitem__(item)
            return True
        except KeyError:
            return False

    def get(self, key, *args):
        """Case-insensitive version of `dict.get`."""
        if len(args)>1:
            raise ValueError(f'Accepts only 1-2 arguments (got {len(args)+1}).')
        try:
            if not isinstance(key, str):
                raise KeyError(f'Invalid key {key}. Must be string.')
            return self.__getitem__(key.lower())
        except KeyError as key_error:
            if args:
                return args[0]
            else:
                raise key_error

    def pop(self, key, *args):
        """Case-insensitive version of `dict.pop`."""
        if len(args)>1:
            raise ValueError(f'Accepts only 1-2 arguments (got {len(args)+1}).')
        try:
            key = self._sanitize_key(key)
            value = self._getitem(key) # could raise error
            del self[key]
        except KeyError as key_error:
            if args:
                return args[0]
            else:
                raise key_error
        return value

# Override default colormap dictionary
if not isinstance(mcm.cmap_d, CmapDict):
    mcm.cmap_d = CmapDict(mcm.cmap_d)

#------------------------------------------------------------------------------#
# Color manipulation functions
#------------------------------------------------------------------------------#
def _get_space(space):
    """Verify requested colorspace is valid."""
    space = _space_aliases.get(space, None)
    if space is None:
        raise ValueError(f'Unknown colorspace "{space}".')
    return space

def _get_channel(color, channel, space='hsl'):
    """Gets hue, saturation, or luminance channel value from registered
    string color name. The color name `color` can optionally be a string
    with the format ``'color+x'`` or ``'color-x'``, where `x` specifies
    the offset from the channel value."""
    # Interpret channel
    channel = _channel_idxs.get(channel, channel)
    if callable(color) or isinstance(color, Number):
        return color
    if channel not in (0,1,2):
        raise ValueError('Channel must be in [0,1,2].')
    # Interpret string or RGB tuple
    offset = 0
    if isinstance(color, str):
        regex = '([-+]\S*)$' # user can optionally offset from color; don't filter to just numbers, want to raise our own error if user messes up
        match = re.search(regex, color)
        if match:
            try:
                offset = float(match.group(0))
            except ValueError:
                raise ValueError(f'Invalid channel identifier "{color}".')
            color = color[:match.start()]
    return offset + to_xyz(to_rgb(color, 'rgb'), space)[channel]

def shade(color, shade=0.5):
    """Changes the "shade" of a color by scaling its luminance channel by `shade`."""
    try:
        color = mcolors.to_rgb(color) # ensure is valid color
    except Exception:
        raise ValueError(f'Invalid RGBA argument {color}. Registered colors are: {", ".join(mcolors._colors_full_map.keys())}.')
    color = [*colormath.rgb_to_hsl(*color)]
    color[2] = max([0, min([color[2]*shade, 100])]) # multiply luminance by this value
    color = [*colormath.hsl_to_rgb(*color)]
    return tuple(color)

def to_rgb(color, space='rgb'):
    """Generalization of matplotlib's `~matplotlib.colors.to_rgb`. Translates
    colors from *any* colorspace to rgb. Also will convert color
    strings to tuple. Inverse of `to_xyz`."""
    # First the RGB input
    # NOTE: Need isinstance here because strings stored in numpy arrays
    # are actually subclasses thereof!
    if isinstance(color, str):
        try:
            color = mcolors.to_rgb(color) # ensure is valid color
        except Exception:
            raise ValueError(f'Invalid RGBA argument {color}. Registered colors are: {", ".join(mcolors._colors_full_map.keys())}.')
    elif space=='rgb':
        color = color[:3] # trim alpha
        if any(c>1 for c in color):
            color = [c/255 for c in color] # scale to within 0-1
    # Next the perceptually uniform versions
    elif space=='hsv':
        color = colormath.hsl_to_rgb(*color)
    elif space=='hpl':
        color = colormath.hpluv_to_rgb(*color)
    elif space=='hsl':
        color = colormath.hsluv_to_rgb(*color)
    elif space=='hcl':
        color = colormath.hcl_to_rgb(*color)
    else:
        raise ValueError('Invalid RGB value.')
    return color

def to_xyz(color, space):
    """Translates from RGB space to colorspace `space`. Inverse of `to_rgb`."""
    # Run tuple conversions
    # NOTE: Don't pass color tuple, because we may want to permit out-of-bounds RGB values to invert conversion
    if isinstance(color, str):
        color = mcolors.to_rgb(color) # convert string
    else:
        color = color[:3]
    if space=='hsv':
        color = colormath.rgb_to_hsl(*color) # rgb_to_hsv would also work
    elif space=='hpl':
        color = colormath.rgb_to_hpluv(*color)
    elif space=='hsl':
        color = colormath.rgb_to_hsluv(*color)
    elif space=='hcl':
        color = colormath.rgb_to_hcl(*color)
    elif space=='rgb':
        pass
    else:
        raise ValueError(f'Invalid colorspace {space}.')
    return color

#------------------------------------------------------------------------------#
# Helper functions
#------------------------------------------------------------------------------#
def _transform_cycle(color):
    """Transforms colors C0, C1, etc. into their corresponding color strings.
    May be necessary trying to change the color cycler."""
    # Optional exit
    if not isinstance(color, str):
        return color
    elif not re.match('^C[0-9]$', color):
        return color
    # Transform color to actual cycle color
    else:
        cycler = rcParams['axes.prop_cycle'].by_key()
        if 'color' not in cycler:
            cycle = ['k']
        else:
            cycle = cycler['color']
        return cycle[int(color[-1])]

def _clip_colors(colors, mask=True, gray=0.2, verbose=False):
    """
    Clips impossible colors rendered in an HSl-to-RGB colorspace conversion.
    Used by `PerceptuallyUniformColormap`. If `mask` is ``True``, impossible
    colors are masked out

    Parameters
    ----------
    colors : list of length-3 tuples
        The RGB colors.
    mask : bool, optional
        Whether to mask out (set to `gray` color) or clip (limit
        range of each channel to 0-1) the out-of-range RGB channels.
    gray : float, optional
        The identical RGB channel values (gray color) to be used if `mask`
        is ``True``.
    verbose : bool, optional
        Whether to print message if colors are clipped.
    """
    # Notes:
    # I could use `numpy.clip` (`matplotlib.colors` uses this under the hood),
    # but we want to display messages. And anyway, premature efficiency is
    # the root of all evil, we're manipulating like 1000 colors max here, so
    # it's no big deal.
    message = 'Invalid' if mask else 'Clipped'
    colors = np.array(colors) # easier
    under = (colors<0)
    over  = (colors>1)
    if mask:
        colors[(under | over)] = gray
    else:
        colors[under] = 0
        colors[over]  = 1
    if verbose:
        for i,name in enumerate('rgb'):
            if under[:,i].any():
                warnings.warn(f'{message} "{name}" channel (<0).')
            if over[:,i].any():
                warnings.warn(f'{message} "{name}" channel (>1).')
    return colors

def _clip_cmap(cmap, left=None, right=None, name=None, N=None):
    """Helper function that cleanly divides linear segmented colormaps and
    subsamples listed colormaps. Full documentation is in `Colormap`."""
    # Bail out
    if left is None and right is None:
        return cmap
    # Simple process for listed colormap, just truncate the colors
    name = name or 'no_name'
    if isinstance(cmap, mcolors.ListedColormap):
        try:
            return mcolors.ListedColormap(cmap.colors[left:right])
        except Exception:
            raise ValueError(f'Invalid slice {slice(left,right)} for listed colormap.')

    # Trickier for segment data maps
    # Initial stuff
    left = left or 0
    right = right or 1
    # Resample the segmentdata arrays
    data = {}
    dict_ = {key:value for key,value in cmap._segmentdata.items() if 'gamma' not in key}
    gammas = {'saturation':'gamma1', 'luminance':'gamma2'}
    for key,xyy in dict_.items():
        # Get coordinates
        xyy = np.array(xyy)
        x   = xyy[:,0]
        xleft,  = np.where(x>left)
        xright, = np.where(x<right)
        if len(xleft)==0:
            raise ValueError(f'Invalid x minimum {left}.')
        if len(xright)==0:
            raise ValueError(f'Invalid x maximum {right}.')
        # Slice
        # l is the first point where x>0 or x>left, should be at least 1
        # r is the last point where r<1 or r<right
        l, r = xleft[0], xright[-1]
        ixyy = xyy[l:r+1,:].copy()
        xl = xyy[l-1,1:] + (left - x[l-1])*(xyy[l,1:] - xyy[l-1,1:])/(x[l] - x[l-1])
        ixyy = np.concatenate(([[left, *xl]], ixyy), axis=0)
        xr = xyy[r,1:] + (right - x[r])*(xyy[r+1,1:] - xyy[r,1:])/(x[r+1] - x[r])
        ixyy = np.concatenate((ixyy, [[right, *xr]]), axis=0)
        ixyy[:,0] = (ixyy[:,0] - left)/(right - left)
        data[key] = ixyy
        # Retain the corresponding 'gamma' *segments*
        # Need more testing but so far so good
        if key in gammas:
            gamma = cmap._segmentdata[gammas[key]]
            if np.iterable(gamma):
                gamma = gamma[l-1:r+1]
            data[gammas[key]] = gamma
    # And finally rebuild map
    kwargs = {}
    if hasattr(cmap, '_space'):
        kwargs['space'] = cmap._space
    return type(cmap)(name, data, N=cmap.N, **kwargs)

def _shift_cmap(cmap, shift=None, name=None):
    """Shift a cyclic colormap by `shift` degrees out of 360 degrees."""
    # Bail out
    if not shift:
        return cmap
    # Simple process for listed colormap, just rotate the colors
    name = name or 'no_name'
    if isinstance(cmap, mcolors.ListedColormap):
        shift = shift % len(cmap.colors)
        colors = [*cmap.colors] # ensure list
        colors = colors[shift:] + colors[:shift]
        return mcolors.ListedColormap(colors, name=name, N=len(colors))

    # Trickier for smooth colormaps, must shift coordinates
    # TODO: This won't work for lo-res colormaps or percpetually
    # uniform maps with only a couple coordiante transitions, right?
    data = cmap._segmentdata.copy()
    for key,orig in cmap._segmentdata.items():
        # Drop an end color
        orig = np.array(orig)
        orig = orig[1:,:]
        array = orig.copy()
        array[:,0] -= shift/360
        array[:,0] %= 1
        # Add end color back in
        array = array[array[:,0].argsort(),:]
        array = np.concatenate((array[-1:,:], array), axis=0)
        array[:1,0] = array[1:2,0] - np.diff(array[1:3,0])
        # Normalize x-range
        array[:,0] -= array[:,0].min()
        array[:,0] /= array[:,0].max()
        data[key] = array
    # Generate shifted colormap
    cmap = mcolors.LinearSegmentedColormap(name, data, N=cmap.N)
    cmap._cyclic = True
    return cmap

def _merge_cmaps(*imaps, ratios=1, name=None, N=512, **kwargs):
    """Merges arbitrary colormaps. This is used when you pass multiple `imaps`
    to the `Colormap` function. Full documentation is in `Colormap`."""
    # Bail out
    if len(imaps)==1:
        return imaps[0]
    types = {type(cmap) for cmap in imaps}
    if len(types)!=1:
        raise ValueError(f'Mixed colormap types {types}. Maps must all be LinearSegmentedColormap or PerceptuallyUniformColormap.')
    type_ = types.pop()
    # Simple process for listed colormap, just combine the colors
    name = name or 'no_name'
    if all(isinstance(cmap, mcolors.ListedColormap) for cmap in imaps):
        colors = [color for cmap in imaps for color in cmap.colors]
        return mcolors.ListedColormap(colors, name=name, N=len(colors))

    # Tricker for smooth maps
    # Initial stuff
    kwargs = {}
    segmentdata = {}
    ratios = ratios or 1
    if isinstance(ratios, Number):
        ratios = [1]*len(imaps)
    ratios = np.array(ratios)/np.sum(ratios) # so if 4 cmaps, will be 1/4
    x0 = np.concatenate([[0], np.cumsum(ratios)])
    xw = x0[1:] - x0[:-1] # weights for averages
    # PerceptuallyUniformColormaps checks
    if type_ is PerceptuallyUniformColormap:
        spaces = {cmap._space for cmap in imaps}
        if len(spaces)>1:
            raise ValueError(f'Cannot merge colormaps in the different HSL spaces {repr(spaces)}.')
        kwargs['space'] = spaces.pop()
        gammas = {0:'saturation', 1:'luminance'}
        for i,key in enumerate(('gamma1', 'gamma2')):
            if key not in segmentdata:
                segmentdata[key] = []
            for cmap in imaps:
                gamma = cmap._segmentdata[key]
                if not np.iterable(gamma):
                    gamma = [gamma]*(len(cmap._segmentdata[gammas[i]])-1) # length is *number* of rows in segmentdata
                segmentdata[key].extend([*gamma])
    # Combine the segmentdata, and use the y1/y2 slots at merge points so
    # we never interpolate between end colors of different colormaps
    keys = {key for cmap in imaps for key in cmap._segmentdata.keys() if 'gamma' not in key}
    for key in keys:
        # Combine xyy data
        datas = []
        callable_ = [callable(cmap._segmentdata[key]) for cmap in imaps]
        if not all(callable_) and any(callable_):
            raise ValueError('Mixed callable and non-callable colormap values.')
        if all(callable_): # expand range from x-to-w to 0-1
            for x,w,cmap in zip(x0[:-1], xw, imaps):
                data = lambda x: data((x - x0)/w) # WARNING: untested!
                datas.append(data)
        else:
            for x,w,cmap in zip(x0[:-1], xw, imaps):
                data = np.array(cmap._segmentdata[key])
                data[:,0] = x + w*data[:,0]
                datas.append(data)
            for i in range(len(datas)-1):
                datas[i][-1,2] = datas[i+1][0,2]
                datas[i+1] = datas[i+1][1:,:]
            data = np.concatenate(datas, axis=0)
            data[:,0] = data[:,0]/data[:,0].max(axis=0) # scale to make maximum exactly 1 (avoid floating point errors)
        segmentdata[key] = data
    return type_(name, segmentdata, N=N, **kwargs)

def _make_segmentdata_array(values, ratios=None, reverse=False, **kwargs):
    """Constructs a list of linear segments for an individual channel.
    This was made so that user can input e.g. a callable function for
    one channel, but request linear interpolation for another one."""
    # Handle function handles
    if callable(values):
        if reverse:
            values = lambda x: values(1-x)
        return values # just return the callable
    values = np.atleast_1d(values)
    if len(values)==1:
        value = values[0]
        return [(0, value, value), (1, value, value)] # just return a constant transition

    # Get x coordinates
    if not np.iterable(values):
        raise TypeError('Colors must be iterable.')
    if ratios is not None:
        xvals = np.atleast_1d(ratios) # could be ratios=1, i.e. dummy
        if len(xvals) != len(values) - 1:
            raise ValueError(f'Got {len(values)} values, but {len(ratios)} ratios.')
        xvals = np.concatenate(([0], np.cumsum(xvals)))
        xvals = xvals/np.max(xvals) # normalize to 0-1
    else:
        xvals = np.linspace(0,1,len(values))

    # Build vector
    array = []
    slicer = slice(None,None,-1) if reverse else slice(None)
    for x,value in zip(xvals,values[slicer]):
        array.append((x, value, value))
    return array

def make_mapping_array(N, data, gamma=1.0, reverse=False):
    r"""
    Mostly a copy of `~matplotlib.colors.makeMappingArray`, but allows
    *circular* hue gradations along 0-360, disables clipping of
    out-of-bounds channel values, and with fancier "gamma" scaling.

    Parameters
    ----------
    N : int
        Number of points in the generated lookup table.
    data : 2D array-like
        List of :math:`(x, y_0, y_1)` tuples specifying the channel jump (from
        :math:`y_0` to :math:`y_1`) and the :math:`x` coordinate of that
        transition (ranges between 0 and 1).
        See `~matplotlib.colors.LinearSegmentedColormap` for details.
    gamma : float or list of float, optional
        To obtain channel values between coordinates :math:`x_i` and
        :math:`x_{i+1}` in rows :math:`i` and :math:`i+1` of `data`,
        we use the formula:

        .. math::

            y = y_{1,i} + w_i^{\gamma_i}*(y_{0,i+1} - y_{1,i})

        where :math:`\gamma_i` corresponds to `gamma` and the weight
        :math:`w_i` ranges from 0 to 1 between rows ``i`` and ``i+1``.
        If `gamma` is float, it applies to every transition. Otherwise,
        its length must equal ``data.shape[0]-1``.
    reverse : bool, optional
        If ``True``, :math:`w_i^{\gamma_i}` is replaced with
        :math:`1 - (1 - w_i)^{\gamma_i}` -- that is, when `gamma` is greater
        than 1, this weights colors toward *higher* channel values instead
        of lower channel values.

        This is implemented in case we want to apply *equal* "gamma scaling"
        to different HSL channels in different directions. Usually, this
        is done to weight low data values with higher luminance *and* lower
        saturation, thereby emphasizing "extreme" data values with stronger
        colors.
    """
    # Optionally allow for ***callable*** instead of linearly interpolating
    # between line segments
    gammas = np.atleast_1d(gamma)
    if (gammas < 0.01).any() or (gammas > 10).any():
        raise ValueError('Gamma can only be in range [0.01,10].')
    if callable(data):
        if len(gammas)>1:
            raise ValueError('Only one gamma allowed for functional segmentdata.')
        x = np.linspace(0, 1, N)**gamma
        lut = np.array(data(x), dtype=float)
        return lut

    # Get array
    try:
        data = np.array(data)
    except Exception:
        raise TypeError('Data must be convertible to an array.')
    shape = data.shape
    if len(shape) != 2 or shape[1] != 3:
        raise ValueError('Data must be nx3 format.')
    if len(gammas)!=1 and len(gammas)!=shape[0]-1:
        raise ValueError(f'Need {shape[0]-1} gammas for {shape[0]}-level mapping array, but got {len(gamma)}.')
    if len(gammas)==1:
        gammas = np.repeat(gammas, shape[:1])

    # Get indices
    x  = data[:, 0]
    y0 = data[:, 1]
    y1 = data[:, 2]
    if x[0] != 0.0 or x[-1] != 1.0:
        raise ValueError('Data mapping points must start with x=0 and end with x=1.')
    if (np.diff(x) < 0).any():
        raise ValueError('Data mapping points must have x in increasing order.')
    x = x*(N - 1)

    # Get distances from the segmentdata entry to the *left* for each requested
    # level, excluding ends at (0,1), which must exactly match segmentdata ends
    xq = (N - 1)*np.linspace(0, 1, N)
    ind = np.searchsorted(x, xq)[1:-1] # where xq[i] must be inserted so it is larger than x[ind[i]-1] but smaller than x[ind[i]]
    distance = (xq[1:-1] - x[ind - 1])/(x[ind] - x[ind - 1])
    # Scale distances in each segment by input gamma
    # The ui are starting-points, the ci are counts from that point
    # over which segment applies (i.e. where to apply the gamma)
    _, uind, cind = np.unique(ind, return_index=True, return_counts=True)
    for i,(ui,ci) in enumerate(zip(uind,cind)): # i will range from 0 to N-2
        # Test if 1
        gamma = gammas[ind[ui]-1] # the relevant segment is to *left* of this number
        if gamma==1:
            continue
        # By default, weight toward a *lower* channel value (i.e. bigger
        # exponent implies more colors at lower value)
        # Again, the relevant 'segment' is to the *left* of index returned by searchsorted
        ir = False
        if ci>1: # i.e. more than 1 color in this 'segment'
            ir = ((y0[ind[ui]] - y1[ind[ui]-1]) < 0) # by default want to weight toward a *lower* channel value
        if reverse:
            ir = (not ir)
        if ir:
            distance[ui:ui + ci] = 1 - (1 - distance[ui:ui + ci])**gamma
        else:
            distance[ui:ui + ci] **= gamma

    # Perform successive linear interpolations all rolled up into one equation
    lut = np.zeros((N,), float)
    lut[1:-1] = distance*(y0[ind] - y1[ind - 1]) + y1[ind - 1]
    lut[0]  = y1[0]
    lut[-1] = y0[-1]
    return lut

#------------------------------------------------------------------------------#
# Generalized colormap/cycle constructors
#------------------------------------------------------------------------------#
def colors(*args, **kwargs):
    """Alias for `Cycle`."""
    return Cycle(*args, **kwargs)

def Colormap(*args, name=None, cyclic=None, fade=None,
        shift=None, cut=None, left=None, right=None, reverse=False,
        ratios=1, gamma=None, gamma1=None, gamma2=None,
        save=False, N=None,
        **kwargs):
    """
    Convenience function for generating and merging colormaps
    in a variety of ways. See also `~proplot.axes.wrapper_cmap`.

    Parameters
    ----------
    *args : `~matplotlib.colors.Colormap`, dict, list of str, or str
        Each arg generates a single colormap. If ``len(args)>1``, the colormaps
        are merged.

        If the arg is a `~matplotlib.colors.Colormap`, nothing more is done.
        Otherwise, the colormap is generated as follows:

        * If arg is a str and is a "registered" colormap name or color cycle
          name, that `~matplotlib.colors.LinearSegmentedColormap` or
          `~matplotlib.colors.ListedColormap` is used.
        * If arg is a str and is a color string, a
          monochromatic colormap is generated with `monochrome_cmap`.
        * If arg is a list of color strings or RGB tuples, the list is used to
          make a `~matplotlib.colors.ListedColormap`.
        * If arg is dict, there are two options: if the dict contains the keys
          ``'red'``, ``'green'``, and ``'blue'``, it is passed to the
          `~matplotlib.colors.LinearSegmentedColormap` initializer. Otherwise,
          the dict is passed to the `PerceptuallyUniformColormap` initializer
          or the `~PerceptuallyUniformColormap.from_hsl` static method.

    name : None or str, optional
        Name of the resulting colormap. Default name is ``'no_name'``.
        The resulting colormap can then be invoked by passing ``cmap='name'``
        to plotting functions like `~matplotlib.axes.Axes.contourf`.
    cyclic : bool, optional
        Whether the colormap is cyclic. Will cause `~proplot.axes.wrapper_cmap`
        to pass this flag to `BinNorm`. This will prevent having the same color
        on either end of the colormap.
    fade : None or float, optional
        The maximum luminosity, between 0 and 100, used when generating
        `monochrome_cmap` colormaps. The default is ``100``.
    shift : None, or float or list of float, optional
        For `~matplotlib.colors.LinearSegmentedColormap` maps, optionally
        rotate the colors by `shift` degrees out of 360 degrees. This is
        mainly useful for "cyclic" colormaps.
        For example, ``shift=180`` moves the
        edge colors to the center of the colormap.

        For `~matplotlib.colors.ListedColormap` maps, optionally rotate
        the color list by `shift` places. For example, ``shift=2`` moves the
        start of the color cycle two places to the right.
    left, right : None or float or list of float, optional
        For `~matplotlib.colors.LinearSegmentedColormap` maps, optionally
        delete colors on the left and right sides of the
        colormap(s). For example, ``left=0.1`` deletes the leftmost 10% of
        the colormap; ``right=0.9`` deletes the rightmost 10%.

        For `~matplotlib.colors.ListedColormap` maps, optionally slice
        the the color list using ``cmap.colors = cmap.colors[left:right]``.
        For example, ``left=1`` with ``right=None`` deletes the first color.

        If list, length must match ``len(args)``, and applies to *each*
        colormap in the list before they are merged. If float, applies
        to the *merged* colormap. No difference if ``len(args)`` is 1.
    cut : None or float, optional
        For `~matplotlib.colors.LinearSegmentedColormap` maps, optionally
        cut out colors in the **center**
        of the colormap. This is useful if you want to have a sharper cutoff
        between "negative" and "positive" values in a diverging colormap. For example,
        ``cut=0.1`` cuts out the middle 10% of the colormap.
    reverse : bool or list of bool, optional
        Optionally reverse the colormap(s).
        If list, length must match ``len(args)``, and applies to *each*
        colormap in the list before they are merged. If bool, applies
        to the *merged* colormap. No difference if ``len(args)`` is 1.
    ratios : list of float, optional
        Indicates the ratios used to *combine* the colormaps. Length must
        equal ``len(args)`` (ignored if ``len(args)`` is 1).
        For example, if `args` contains ``['blues', 'reds']`` and `ratios`
        is ``[2, 1]``, this generates a colormap with two-thirds blue
        colors on the left and one-third red colors in the right.
    gamma1, gamma2, gamma : float, optional
        Gamma-scaling for the saturation, luminance, and both channels
        for perceptualy uniform colormaps. See the
        `PerceptuallyUniformColormap` documentation.
    save : bool, optional
        Whether to save the colormap in the folder ``~/.proplot``. The
        folder is created if it does not already exist.

        If the colormap is a `~matplotlib.colors.ListedColormap` (i.e. a
        "color cycle"), the list of hex strings are written to ``name.hex``.

        If the colormap is a `~matplotlib.colors.LinearSegmentedColormap`,
        the segment data dictionary is written to ``name.json``.
    N : None or int, optional
        Number of colors to generate in the hidden lookup table ``_lut``.
        By default, a relatively high resolution of 256 is chosen (see notes).

    Returns
    -------
    `~matplotlib.colors.Colormap`
        A `~matplotlib.colors.LinearSegmentedColormap` or
        `~matplotlib.colors.ListedColormap` instance.

    Note
    ----
    Essentially there are two ways to create discretized color levels from a
    functional, "smooth" colormap:

    1. Make a lo-res lookup table, i.e. use a small `N`.
    2. Make a hi-res lookup table, but discretize the lookup table indices
       generated by your normalizer.

    I have found the second method was easier to implement, more flexible, and
    has a negligible impact on speed. So, every colormap plot generated by
    ProPlot is discretized with `BinNorm` (which has a few extra, fine-tunable
    features compared to the native `~matplotlib.colors.BoundaryNorm`).
    """
    # Initial stuff
    # NOTE: See resampling method described in `this post
    # <https://stackoverflow.com/q/48613920/4970632>`_
    # NOTE: Documentation does not advertise that cut_cmap and shift_cmap
    # tools work with listed colors; that is pretty weird usage, only will
    # come up when trying to use color cycle as colormap. This behavior
    # is only advertised in Cycle constructor.
    N_ = N or rcParams['image.lut']
    imaps = []
    name = name or 'no_name' # must have name, mcolors utilities expect this
    args = args or (None,)
    for i,cmap in enumerate(args):
        # Retrieve Colormap instance. Makes sure lookup table is reset.
        cmap = _default(cmap, rcParams['image.cmap'])
        if isinstance(cmap,str) and cmap in mcm.cmap_d:
            cmap = mcm.cmap_d[cmap]
        if isinstance(cmap, mcolors.ListedColormap):
            pass
        elif isinstance(cmap, mcolors.LinearSegmentedColormap):
            # Resample, allow overriding the gamma
            # Copy over this add-on attribute
            # NOTE: Calling resample means cmaps are un-initialized
            cyclic = getattr(cmap, '_cyclic', False)
            cmap = cmap._resample(N_)
            cmap._cyclic = cyclic
            if isinstance(cmap, PerceptuallyUniformColormap):
                gamma1 = _default(gamma, gamma1)
                gamma2 = _default(gamma, gamma2)
                segmentdata = cmap._segmentdata
                if gamma1:
                    segmentdata['gamma1'] = gamma1
                if gamma2:
                    segmentdata['gamma2'] = gamma2
            elif gamma:
                cmap._gamma = gamma
        # Build colormap on-the-fly
        elif isinstance(cmap, dict):
            # Dictionary of hue/sat/luminance values or 2-tuples representing linear transition
            if {*cmap.keys()} == {'red','green','blue'}:
                cmap = mcolors.LinearSegmentedColormap(name, cmap, N=N_)
            else:
                cmap = PerceptuallyUniformColormap.from_hsl(name, N=N_, **cmap)
        elif not isinstance(cmap, str) and np.iterable(cmap) and all(np.iterable(color) for color in cmap):
            # List of color tuples or color strings, i.e. iterable of iterables
            # Transform C0, C1, etc. to their actual names first
            cmap = [_transform_cycle(color) for color in cmap]
            cmap = mcolors.ListedColormap(cmap, name=name, **kwargs)
        elif isinstance(cmap, str) or (np.iterable(cmap) and len(cmap) in (3,4)):
            # Monochrome colormap based from input color (i.e. single hue)
            # TODO: What if colormap names conflict with color names!
            # TODO: Support for e.g. automatically determining number of samples
            # when cycle declared on-the-fly in call to plot?
            color = to_rgb(_transform_cycle(cmap)) # to ensure is hex code/registered color
            fade = _default(fade, 100)
            cmap = monochrome_cmap(color, fade, name=name, N=N_, **kwargs)
        else:
            raise ValueError(f'Invalid cmap input "{cmap}".')

        # Optionally transform colormap by clipping colors or reversing
        if np.iterable(reverse) and reverse[i]:
            cmap = cmap.reversed()
        cmap = _clip_cmap(cmap, None if not np.iterable(left) else left[i],
                                None if not np.iterable(right) else right[i], N=N)
        imaps += [cmap]

    # Now merge the result of this arbitrary user input
    # Since we are merging cmaps, potentially *many* color transitions; use big number by default
    N_ = N_*len(imaps)
    if len(imaps)>1:
        cmap = _merge_cmaps(*imaps, name=name, ratios=ratios, N=N_)

    # Cut out either edge
    left = None if np.iterable(left) else left
    right = None if np.iterable(right) else right
    if not cut: # non-zero and not None
        cmap = _clip_cmap(cmap, left, right, name=name, N=N)
    # Cut out middle colors of a diverging map
    else:
        cright, cleft = 0.5 - cut/2, 0.5 + cut/2
        lcmap = _clip_cmap(cmap, left, cright)
        rcmap = _clip_cmap(cmap, cleft, right)
        cmap = _merge_cmaps(lcmap, rcmap, name=name, N=N_)
    # Cyclic colormap settings
    if shift: # i.e. is non-zero
        cmap = _shift_cmap(cmap, shift, name=name)
    if cyclic is not None:
        cmap._cyclic = cyclic
    elif not hasattr(cmap, '_cyclic'):
        cmap._cyclic = False
    # Optionally reverse
    if not np.iterable(reverse) and reverse:
        cmap = cmap.reversed()
    # Initialize (the _resample methods generate new colormaps,
    # so current one is uninitializied)
    if not cmap._isinit:
        cmap._init()

    # Perform crude resampling of data, i.e. just generate a low-resolution
    # lookup table instead.
    # NOTE: This approach is no longer favored; instead we generate hi-res
    # lookup table and use BinNorm to discretize colors, much more flexible.
    # if isinstance(cmap, mcolors.LinearSegmentedColormap) and N is not None:
    #     offset = {'neither':-1, 'max':0, 'min':0, 'both':1}
    #     if extend not in offset:
    #         raise ValueError(f'Unknown extend option {extend}.')
    #     cmap = cmap._resample(N - offset[extend]) # see mcm.get_cmap source

    # Register the colormap
    mcm.cmap_d[name] = cmap
    # Optionally save colormap to disk
    if save:
        # Save listed colormap i.e. color cycle
        if isinstance(cmap, mcolors.ListedColormap):
            basename = f'{name}.hex'
            filename = os.path.join(_data_user_cycles, basename)
            with open(filename, 'w') as f:
                f.write(','.join(mcolors.to_hex(color) for color in cmap.colors))
        # Save segment data directly
        else:
            basename = f'{name}.json'
            filename = os.path.join(_data_user_cmaps, basename)
            data = {}
            for key,value in cmap._segmentdata.items():
                data[key] = np.array(value).astype(float).tolist() # from np.float to builtin float, and to list of lists
            if hasattr(cmap, '_space'):
                data['space'] = cmap._space
            with open(filename, 'w') as file:
                json.dump(data, file, indent=4)
        print(f'Saved colormap to "{basename}".')
    return cmap

def Cycle(*args, samples=None, name=None, save=False, **kwargs):
    """
    Simply calls `Colormap`, then returns the corresponding list of colors
    if a `~matplotlib.colors.ListedColormap` was returned
    or draws samples if a `~matplotlib.colors.LinearSegmentedColormap`
    was returned. See also `~proplot.axes.wrapper_cycle`.

    Parameters
    ----------
    *args
        Either ``args`` or ``(*args, samples)``, where ``args`` are passed to
        `Colormap` as ``Colormap(*args)`` and ``samples`` is used in this
        function to sample smooth colormaps (see below).
    samples : float or list of float, optional
        For a `~matplotlib.colors.ListedColormap`, the maximum number of colors
        to select from the list. For a `~matplotlib.colors.LinearSegmentedColormap`,
        either a list of sample coordinates used to draw colors from the map
        or the integer number of colors to draw. If the latter, the sample
        coordinates are ``np.linspace(0, 1, samples)``.
    name : None or str, optional
        Name of the resulting `~matplotlib.colors.ListedColormap`.
        Default name is ``'no_name'``.
    save : bool, optional
        Whether to save the color cycle in the folder ``~/.proplot``. The
        folder is created if it does not already exist. The cycle is saved
        as a list of hex strings to the file ``name.hex``.
    **kwargs
        Passed to `Colormap`.

    Returns
    -------
    `ColorCycle`
        Just a list of colors with a name attribute. This color list is also
        registered under the name `name` as a `~matplotlib.colors.ListedColormap`.
    """
    # Flexible input options
    # TODO: Allow repeating the color cycle with, e.g., different
    # line styles or other properties.
    # 1) User input some number of samples; 99% of time, use this
    # to get samples from a LinearSegmentedColormap
    # (np.iterable(args[-1]) and \ all(isinstance(item,Number) for item in args[-1]))
    name = name or 'no_name'
    # Return the current cycler if empty
    if len(args)==0:
        args = (rcParams['axes.prop_cycle'].by_key()['color'],)
    # Optionally pass (color, fade) or (color, fade, samples) tuples
    else:
        # Draw from smooth colormaps
        # WARNING: When passing cycle=color, wrapper unfurls the RGB tuple,
        # so try to detect that here.
        smooth = False
        if all(isinstance(arg, Number) for arg in args) and len(args) in (3,4):
            args = (args,)
        else:
            if len(args)>=2 and all(isinstance(arg, Number) for arg in args[-2:]):
                args, samples, kwargs['fade'] = args[:-2], args[-2], args[-1]
                smooth = True
            elif isinstance(args[-1], Number):
                args, samples = args[:-1], args[-1]
                smooth = True
        # Input was just list of color strings or RGB tuples, means user
        # wanted this list of colors as the cycle!
        if not smooth and len(args)>1:
            args = (args,)

    # Get list of colors, and construct and register ListedColormap
    cmap = Colormap(*args, **kwargs) # the cmap object itself
    if isinstance(cmap, mcolors.ListedColormap):
        cmap.colors = cmap.colors[:samples] # if samples is None, does nothing
    else:
        samples = _default(samples, 10)
        if isinstance(samples, Number):
            samples = np.linspace(0, 1, samples) # from edge to edge
        elif np.iterable(samples) and all(isinstance(item,Number) for item in samples):
            samples = np.array(samples)
        else:
            raise ValueError(f'Invalid samples "{samples}".')
        cmap = mcolors.ListedColormap(cmap(samples), name=name, N=len(samples))
    # Register the colormap
    cmap.colors = [tuple(color) if not isinstance(color,str) else color for color in cmap.colors]
    mcm.cmap_d[name] = cmap
    # Optionally save
    if save:
        basename = f'{name}.hex'
        filename = os.path.join(_data_user_cycles, basename)
        with open(filename, 'w') as f:
            f.write(','.join(mcolors.to_hex(color) for color in cmap.colors))
    return ColorCycle(cmap.colors, name)

class PerceptuallyUniformColormap(mcolors.LinearSegmentedColormap):
    """Similar to `~matplotlib.colors.LinearSegmentedColormap`, but instead
    of varying the RGB channels, we vary hue, saturation, and luminance in
    either the perceptually uniform HCL colorspace or the HSLuv or HPLuv
    scalings of HCL."""
    def __init__(self, name, segmentdata, space='hsl', mask=False,
        gamma=None, gamma1=None, gamma2=None, **kwargs):
        """
        Parameters
        ----------
        name : str
            The colormap name.
        segmentdata : dict-like
            Dictionary mapping containing the keys ``'hue'``, ``'saturation'``,
            and ``'luminance'``. Values should be lists containing any of
            the following channel specifiers:

                1. Numbers, within the range 0-360 for hue and 0-100 for
                   saturation and luminance.
                2. Color string names or hex tags, in which case the channel
                   value for that color is looked up.

            See `~matplotlib.colors.LinearSegmentedColormap` for details.
        space : {'hsl', 'hcl', 'hpl'}, optional
            The hue, saturation, luminance-style colorspace to use for
            interpreting the channels. See `this page
            <http://www.hsluv.org/comparison/>`_ for a description of each
            colorspace.
        mask : bool, optional
            When we interpolate across HSL space, we can end
            up with "impossible" RGB colors (colors with channel values
            >1).

            If `mask` is ``True``, these "impossible" colors are masked
            out as black. Otherwise, the channels are just clipped to 1.
            Default is ``False``.
        gamma1 : None or float, optional
            If >1, makes low saturation colors more prominent. If <1,
            makes high saturation colors more prominent. Similar to the
            `HCLWizard <http://hclwizard.org:64230/hclwizard/>`_ option.
            See `make_mapping_array` for details.
        gamma2 : None or float, optional
            If >1, makes high luminance colors more prominent. If <1,
            makes low luminance colors more prominent. Similar to the
            `HCLWizard <http://hclwizard.org:64230/hclwizard/>`_ option.
            See `make_mapping_array` for details.
        gamma : None or float, optional
            Use this to identically set `gamma1` and `gamma2` at once.

        Example
        -------
        The following is a valid `segmentdata` dictionary, using color string
        names for the hue instead of numbers between 0 and 360.

        .. code-block:: python

            dict(hue       = [[0, 'red', 'red'], [1, 'blue', 'blue']],
                saturation = [[0, 100, 100], [1, 100, 100]],
                luminance  = [[0, 100, 100], [1, 20, 20]])

        Note
        ----
        `gamma1` emphasizes *low* saturation colors and `gamma2` emphasizes
        *high* luminance colors because this seems to be what the
        ColorBrewer2.0 maps do.  "White" and "pale" values at the center of
        diverging maps and on the left of sequential maps are given
        extra emphasis.
        """
        # Attributes
        # NOTE: Don't allow power scaling for hue because that would be weird.
        # Idea is want to allow skewing so dark/saturated colors are
        # more isolated/have greater intensity.
        # NOTE: We add gammas to the segmentdata dictionary so it can be
        # pickled into .npy file
        space = _get_space(space)
        if 'gamma' in kwargs:
            raise ValueError('Standard gamma scaling disabled. Use gamma1 or gamma2 instead.')
        gamma1 = _default(gamma, gamma1)
        gamma2 = _default(gamma, gamma2)
        segmentdata['gamma1'] = _default(gamma1, segmentdata.get('gamma1', None), 1.0)
        segmentdata['gamma2'] = _default(gamma2, segmentdata.get('gamma2', None), 1.0)
        self._space = space
        self._mask  = mask
        # First sanitize the segmentdata by converting color strings to their
        # corresponding channel values
        keys   = {*segmentdata.keys()}
        target = {'hue', 'saturation', 'luminance', 'gamma1', 'gamma2'}
        if keys != target and keys != {*target, 'alpha'}:
            raise ValueError(f'Invalid segmentdata dictionary with keys {keys}.')
        for key,array in segmentdata.items():
            # Allow specification of channels using registered string color names
            if 'gamma' in key:
                continue
            if callable(array):
                continue
            for i,xyy in enumerate(array):
                xyy = list(xyy) # make copy!
                for j,y in enumerate(xyy[1:]): # modify the y values
                    xyy[j+1] = _get_channel(y, key, space)
                segmentdata[key][i] = xyy
        # Initialize
        # NOTE: Our gamma1 and gamma2 scaling is just fancy per-channel
        # gamma scaling, so disable the standard version.
        super().__init__(name, segmentdata, gamma=1.0, **kwargs)

    def reversed(self, name=None):
        """Returns reversed colormap."""
        if name is None:
            name = self.name + '_r'
        def factory(dat):
            def func_r(x):
                return dat(1.0 - x)
            return func_r
        data_r = {}
        for key,xyy in self._segmentdata.items():
            if key in ('gamma1', 'gamma2', 'space'):
                if 'gamma' in key: # optional per-segment gamma
                    xyy = np.atleast_1d(xyy)[::-1]
                data_r[key] = xyy
                continue
            elif callable(xyy):
                data_r[key] = factory(xyy)
            else:
                data_r[key] = [[1.0 - x, y1, y0] for x, y0, y1 in reversed(xyy)]
        return PerceptuallyUniformColormap(name, data_r, space=self._space)

    def _init(self):
        """As with `~matplotlib.colors.LinearSegmentedColormap`, but converts
        each value in the lookup table from 'input' to RGB."""
        # First generate the lookup table
        channels = ('hue','saturation','luminance')
        reverse = (False, False, True) # gamma weights *low chroma* and *high luminance*
        gammas = (1.0, self._segmentdata['gamma1'], self._segmentdata['gamma2'])
        self._lut_hsl = np.ones((self.N+3, 4), float) # fill
        for i,(channel,gamma,reverse) in enumerate(zip(channels, gammas, reverse)):
            self._lut_hsl[:-3,i] = make_mapping_array(self.N, self._segmentdata[channel], gamma, reverse)
        if 'alpha' in self._segmentdata:
            self._lut_hsl[:-3,3] = make_mapping_array(self.N, self._segmentdata['alpha'])
        self._lut_hsl[:-3,0] %= 360
        # self._lut_hsl[:-3,0] %= 359 # wrong
        # Make hues circular, set extremes (i.e. copy HSL values)
        self._lut = self._lut_hsl.copy() # preserve this, might want to check it out
        self._set_extremes() # generally just used end values in segmentdata
        self._isinit = True
        # Now convert values to RGBA, and clip colors
        for i in range(self.N+3):
            self._lut[i,:3] = to_rgb(self._lut[i,:3], self._space)
        self._lut[:,:3] = _clip_colors(self._lut[:,:3], self._mask)

    def _resample(self, N):
        """Returns a new colormap with *N* entries."""
        return PerceptuallyUniformColormap(self.name, self._segmentdata, self._space, self._mask, N=N)

    @staticmethod
    def from_hsl(name, h=0, s=100, l=[100, 20], c=None, a=None,
            ratios=None, reverse=False, **kwargs):
        """
        Makes a `~PerceptuallyUniformColormap` by specifying the hue, saturation,
        and luminance transitions individually.

        Parameters
        ----------
        h : float, str, or list thereof, optional
            Hue channel value or list of values. Values can be
            any of the following:

            1. Numbers, within the range 0-360 for hue and 0-100 for
               saturation and luminance.
            2. Color string names or hex tags, in which case the channel
               value for that color is looked up.

            If scalar, the hue does not change across the colormap.
        s : float, str, or list thereof, optional
            As with `h`, but for the saturation channel.
        l, c : float, str, or list thereof, optional
            As with `h`, but for the luminance channel.
        a : float, str, or list thereof, optional
            As with `h`, but for the alpha channel (the transparency).
        ratios : None or list of float, optional
            Relative extent of the transitions indicated by the channel
            value lists.

            For example, ``luminance=[100,50,0]`` with ``ratios=[2,1]``
            places the *x*-coordinate where the luminance is 50 at 0.66 --
            the white to gray transition is "slower" than the gray to black
            transition.
        reverse : bool, optional
            Whether to reverse the final colormap.

        Returns
        -------
        `PerceptuallyUniformColormap`
            The colormap.

        Todo
        ----
        Add ability to specify *discrete "jump" transitions*. Currently, this
        only lets you generate colormaps with smooth transitions, and is not
        necessarily suited for e.g. making diverging colormaps.
        """
        # Build dictionary, easy peasy
        s = _default(c, s)
        a = _default(a, 1.0)
        cdict = {}
        for c, channel in zip(('hue','saturation','luminance','alpha'), (h,s,l,a)):
            cdict[c] = _make_segmentdata_array(channel, ratios, reverse, **kwargs)
        cmap = PerceptuallyUniformColormap(name, cdict, **kwargs)
        return cmap

    @staticmethod
    def from_list(name, color_list,
        ratios=None, reverse=False,
        **kwargs):
        """
        Makes a `PerceptuallyUniformColormap` from a list of (hue, saturation,
        luminance) tuples.

        Parameters
        ----------
        name : str
            The colormap name.
        color_list : list of length-3 tuples
            List containing HSL color tuples. The tuples can contain any
            of the following channel value specifiers:

            1. Numbers, within the range 0-360 for hue and 0-100 for
               saturation and luminance.
            2. Color string names or hex tags, in which case the channel
               value for that color is looked up.

        ratios : None or list of float, optional
            Length ``len(color_list)-1`` list of scales for *x*-coordinate
            transitions between colors. Bigger numbers indicate a slower
            transition, smaller numbers indicate a faster transition.
        reverse : bool, optional
            Whether to reverse the result.
        """
        # Dictionary
        cdict = {}
        channels = [*zip(*color_list)]
        if len(channels) not in (3,4):
            raise ValueError(f'Bad color list: {color_list}')
        cs = ['hue', 'saturation', 'luminance']
        if len(channels)==4:
            cs += ['alpha']
        else:
            cdict['alpha'] = 1.0 # dummy function that always returns 1.0
        # Build data arrays
        for c,channel in zip(cs,channels):
            cdict[c] = _make_segmentdata_array(channel, ratios, reverse, **kwargs)
        cmap = PerceptuallyUniformColormap(name, cdict, **kwargs)
        return cmap

def monochrome_cmap(color, fade, reverse=False, space='hpl', name='monochrome', **kwargs):
    """
    Makes a monochromatic "sequential" colormap that blends from near-white
    to the input color.

    Parameters
    ----------
    color : str or (R,G,B) tuple
        Color RGB tuple, hex string, or named color string.
    fade : float or str or (R,G,B) tuple
        The luminance channel strength, or color from which to take the luminance channel.
    reverse : bool, optional
        Whether to reverse the colormap.
    space : {'hsl', 'hcl', 'hpl'}, optional
        Colorspace in which the luminance is varied.
    name : str, optional
        Colormap name. Default is ``'monochrome'``.

    Other parameters
    ----------------
    **kwargs
        Passed to `PerceptuallyUniformColormap.from_hsl` static method.
    """
    # Get colorspace
    # NOTE: If you use HSL space, will get very saturated colors in the middle
    # of the map (around 50% luminance); otherwise chroma won't change
    h, s, l = to_xyz(to_rgb(color), space)
    if isinstance(fade, Number): # allow just specifying the luminance channel
        fs, fl = s, fade # fade to *same* saturation by default
        fs = s/2
    else:
        _, fs, fl = to_xyz(to_rgb(fade), space)
    index = slice(None,None,-1) if reverse else slice(None)
    return PerceptuallyUniformColormap.from_hsl(name, h,
            [fs,s][index], [fl,l][index], space=space, **kwargs)

#------------------------------------------------------------------------------#
# Return arbitrary normalizer
#------------------------------------------------------------------------------
def Norm(norm_in, levels=None, values=None, norm=None, **kwargs):
    """
    Returns an arbitrary `~matplotlib.colors.Normalize` instance.

    Parameters
    ----------
    norm_in : str or `~matplotlib.colors.Normalize`
        Key name for the normalizer. The recognized normalizer key names
        are as follows:

        ===============  =================================
        Key              Class
        ===============  =================================
        ``'none'``       `~matplotlib.colors.NoNorm`
        ``'null'``       `~matplotlib.colors.NoNorm`
        ``'zero'``       `MidpointNorm`
        ``'midpoint'``   `MidpointNorm`
        ``'segments'``   `LinearSegmentedNorm`
        ``'segmented'``  `LinearSegmentedNorm`
        ``'log'``        `~matplotlib.colors.LogNorm`
        ``'linear'``     `~matplotlib.colors.Normalize`
        ``'power'``      `~matplotlib.colors.PowerNorm`
        ``'symlog'``     `~matplotlib.colors.SymLogNorm`
        ===============  =================================

    levels, values : array-like
        The level edges (`levels`) or centers (`values`) passed
        to `LinearSegmentedNorm`.
    norm : None or normalizer spec, optional
        The normalizer for *pre-processing*. Used only for
        the `LinearSegmentedNorm` normalizer.
    **kwargs
        Passed to the `~matplotlib.colors.Normalize` initializer.
        See `this tutorial <https://matplotlib.org/tutorials/colors/colormapnorms.html>`_
        for more info.

    Returns
    -------
    `~matplotlib.colors.Normalize`
        A `~matplotlib.colors.Normalize` instance.
    """
    norm, norm_preprocess = norm_in, norm
    if isinstance(norm, mcolors.Normalize):
        return norm
    if levels is None and values is not None:
        levels = utils.edges(values)
    if isinstance(norm, str):
        # Get class
        norm_out = normalizers.get(norm, None)
        if norm_out is None:
            raise ValueError(f'Unknown normalizer "{norm}". Options are {", ".join(normalizers.keys())}.')
        # Instantiate class
        if norm_out is MidpointNorm:
            if not np.iterable(levels):
                raise ValueError(f'Need levels for normalizer "{norm}". Received levels={levels}.')
            kwargs.update({'vmin':min(levels), 'vmax':max(levels)})
        elif norm_out is LinearSegmentedNorm:
            if not np.iterable(levels):
                raise ValueError(f'Need levels for normalizer "{norm}". Received levels={levels}.')
            kwargs.update({'levels':levels, 'norm':norm_preprocess})
        norm_out = norm_out(**kwargs) # initialize
    else:
        raise ValueError(f'Unknown norm "{norm_out}".')
    return norm_out

#------------------------------------------------------------------------------
# Very important normalization class.
#------------------------------------------------------------------------------
# WARNING: Many methods in ColorBarBase tests for class membership, crucially
# including _process_values(), which if it doesn't detect BoundaryNorm will
# end up trying to infer boundaries from inverse() method. So make it parent class.
class BinNorm(mcolors.BoundaryNorm):
    """
    This normalizer is used for all colormap plots. It can be thought of as a
    "parent" normalizer: it first scales the data according to any
    arbitrary `~matplotlib.colors.Normalize` class, then maps the normalized
    values ranging from 0-1 into **discrete** levels.

    This maps to colors by the closest **index** in the color list. Even if
    your levels edges are weirdly spaced (e.g. [-1000, 100, 0,
    100, 1000] or [0, 10, 12, 20, 22]), the "colormap coordinates" for these
    levels will be [0, 0.25, 0.5, 0.75, 1].
    """
    def __init__(self, levels, norm=None, clip=False, step=1.0, extend='neither'):
        """
        Parameters
        ----------
        levels : list of float
            The discrete data levels.
        norm : None or `~matplotlib.colors.Normalize`, optional
            The normalizer used to transform `levels` and all data passed
            to `BinNorm.__call__` *before* discretization.
        step : float, optional
            The intensity of the transition to out-of-bounds color, as a
            faction of the *average* step between in-bounds colors. The
            default is ``1``.
        extend : {'neither', 'both', 'min', 'max'}, optional
            Which direction colors will be extended. No matter the `extend`
            option, `BinNorm` ensures colors always extend through the
            extreme end colors.
        clip : bool, optional
            A `~matplotlib.colors.Normalize` option.

        Note
        ----
        If you are using a diverging colormap with ``extend='max'`` or
        ``extend='min'``, the center will get messed up. But that is very strange
        usage anyway... so please just don't do that :)
        """
        # Declare boundaries, vmin, vmax in True coordinates.
        # Notes:
        # * Idea is that we bin data into len(levels) discrete x-coordinates,
        #   and optionally make out-of-bounds colors the same or different
        # * Don't need to call parent __init__, this is own implementation
        #   Do need it to subclass BoundaryNorm, so ColorbarBase will detect it
        #   See BoundaryNorm: https://github.com/matplotlib/matplotlib/blob/master/lib/matplotlib/colors.py
        levels = np.atleast_1d(levels)
        if levels.size<=1:
            raise ValueError('Need at least two levels.')
        elif ((levels[1:]-levels[:-1])<=0).any():
            raise ValueError(f'Levels {levels} passed to Normalize() must be monotonically increasing.')
        if extend not in ('both','min','max','neither'):
            raise ValueError(f'Unknown extend option "{extend}". Choose from "min", "max", "both", "neither".')

        # Determine color ids for levels, i.e. position in 0-1 space
        # Length of these ids should be N + 1 -- that is, N - 1 colors
        # for values in-between levels, plus 2 colors for out-of-bounds.
        # * For same out-of-bounds colors, looks like [0, 0, ..., 1, 1]
        # * For unique out-of-bounds colors, looks like [0, X, ..., 1 - X, 1]
        #   where the offset X equals step/len(levels).
        # First get coordinates
        if not norm:
            norm = mcolors.Normalize() # WARNING: Normalization to 0-1 must always take place first, required by colorbar_factory ticks manager.
        x_b = norm(levels)
        x_m = (x_b[1:] + x_b[:-1])/2 # get level centers after norm scaling
        y = (x_m - x_m.min())/(x_m.max() - x_m.min())
        if isinstance(y, ma.core.MaskedArray):
            y = y.filled(np.nan)
        y = y[np.isfinite(y)]
        # Account for out of bounds colors
        # WARNING: For some reason must clip manually for LogNorm, or
        # end up with unpredictable fill value, weird "out-of-bounds" colors
        offset = 0
        scale = 1
        eps = step/levels.size
        if extend in ('min','both'):
            offset = eps
            scale -= eps
        if extend in ('max','both'):
            scale -= eps
        y = np.concatenate(([0], offset + scale*y, [1])) # insert '0' (arg 3) before index '0' (arg 2)
        self._norm = norm
        self._x_b = x_b
        self._y = y
        if isinstance(norm, mcolors.LogNorm):
            self._norm_clip = (5e-249, None)
        else:
            self._norm_clip = None

        # Add builtin properties
        # NOTE: Are vmin/vmax even used?
        self.boundaries = levels
        self.vmin = levels.min()
        self.vmax = levels.max()
        self.clip = clip
        self.N = levels.size

    def __call__(self, xq, clip=None):
        """Normalizes data values to the range 0-1."""
        # Follow example of LinearSegmentedNorm, but perform no interpolation,
        # just use searchsorted to bin the data.
        # Note the bins vector includes out-of-bounds negative (searchsorted
        # index 0) and out-of-bounds positive (searchsorted index N+1) values
        clip = self._norm_clip
        if clip:
            xq = np.clip(xq, *clip)
        xq = self._norm(np.atleast_1d(xq))
        yq = self._y[np.searchsorted(self._x_b, xq)] # which x-bin does each point in xq belong to?
        return ma.masked_array(yq, np.isnan(xq))

    def inverse(self, yq):
        """Raises error -- inversion after discretization is impossible."""
        raise RuntimeError('BinNorm is not invertible.')

#------------------------------------------------------------------------------#
# Normalizers intended to *pre-scale* levels passed to BinNorm
#------------------------------------------------------------------------------#
class LinearSegmentedNorm(mcolors.Normalize):
    """
    This is the default normalizer paired with `BinNorm` whenever `levels`
    are non-linearly spaced.

    It follows the example of the `~matplotlib.colors.LinearSegmentedColormap`
    source code and performs efficient, vectorized linear interpolation
    between the provided boundary levels. That is, the normalized value is
    linear with respect to its average **index** in the `levels` vector. This
    allows color transitions with uniform intensity across **arbitrarily
    spaced**, monotonically increasing points.

    Can be used by passing ``norm='segments'`` to any command accepting
    ``cmap``. The default midpoint is zero.
    """
    def __init__(self, levels, clip=False, **kwargs):
        """
        Parameters
        ----------
        levels : list of float
            The discrete data levels.
        **kwargs, clip
            Passed to `~matplotlib.colors.Normalize`.
        """
        # Save levels
        levels = np.atleast_1d(levels)
        if levels.size<=1:
            raise ValueError('Need at least two levels.')
        elif ((levels[1:]-levels[:-1])<=0).any():
            raise ValueError(f'Levels {levels} passed to LinearSegmentedNorm must be monotonically increasing.')
        super().__init__(np.nanmin(levels), np.nanmax(levels), clip) # second level superclass
        self._x = levels
        self._y = np.linspace(0, 1, len(levels))

    def __call__(self, xq, clip=None):
        """Normalizes data values to the range 0-1. Inverse operation
        of `~LinearSegmentedNorm.inverse`."""
        # Follow example of make_mapping_array for efficient, vectorized
        # linear interpolation across multiple segments.
        # Notes:
        # * Normal test puts values at a[i] if a[i-1] < v <= a[i]; for
        #   left-most data, satisfy a[0] <= v <= a[1]
        # * searchsorted gives where xq[i] must be inserted so it is larger
        #   than x[ind[i]-1] but smaller than x[ind[i]]
        x = self._x # from arbitrarily spaced monotonic levels
        y = self._y # to linear range 0-1
        xq = np.atleast_1d(xq)
        ind = np.searchsorted(x, xq)
        ind[ind==0] = 1
        ind[ind==len(x)] = len(x) - 1 # actually want to go to left of that
        distance = (xq - x[ind - 1])/(x[ind] - x[ind - 1])
        yq = distance*(y[ind] - y[ind - 1]) + y[ind - 1]
        return ma.masked_array(yq, np.isnan(xq))

    def inverse(self, yq):
        """Inverse operation of `~LinearSegmentedNorm.__call__`."""
        x = self._x
        y = self._y
        yq = np.atleast_1d(yq)
        ind = np.searchsorted(y, yq)
        ind[ind==0] = 1
        ind[ind==len(y)] = len(y) - 1
        distance = (yq - y[ind - 1])/(y[ind] - y[ind - 1])
        xq = distance*(x[ind] - x[ind - 1]) + x[ind - 1]
        return ma.masked_array(xq, np.isnan(yq))

class MidpointNorm(mcolors.Normalize):
    """
    Ensures a "midpoint" always lies at the central colormap color.
    Can be used by passing ``norm='midpoint'`` to any command accepting
    ``cmap``. The default midpoint is zero.
    """
    def __init__(self, midpoint=0, vmin=None, vmax=None, clip=None):
        """
        Parameters
        ----------
        midpoint : float, optional
            The midpoint, or the data value corresponding to the normalized
            value ``0.5`` -- halfway down the colormap.
        vmin, vmax, clip
            The minimum and maximum data values, and the clipping setting.
            Passed to `~matplotlib.colors.Normalize`.

        Note
        ----
        See `this stackoverflow thread <https://stackoverflow.com/q/25500541/4970632>`_.
        """
        # Bigger numbers are too one-sided
        super().__init__(vmin, vmax, clip)
        self._midpoint = midpoint

    def __call__(self, xq, clip=None):
        """Normalizes data values to the range 0-1. Inverse operation of
        `~MidpointNorm.inverse`."""
        # Get middle point in 0-1 coords, and value
        # Notes:
        # * Look up these three values in case vmin/vmax changed; this is
        #   a more general normalizer than the others. Others are 'parent'
        #   normalizers, meant to be static more or less.
        # * searchsorted gives where xq[i] must be inserted so it is larger
        #   than x[ind[i]-1] but smaller than x[ind[i]]
        #   x, y = [self.vmin, self._midpoint, self.vmax], [0, 0.5, 1]
        if self.vmin >= self._midpoint or self.vmax <= self._midpoint:
            raise ValueError(f'Midpoint {self._midpoint} outside of vmin {self.vmin} and vmax {self.vmax}.')
        x = np.array([self.vmin, self._midpoint, self.vmax])
        y = np.array([0, 0.5, 1])
        xq = np.atleast_1d(xq)
        ind = np.searchsorted(x, xq)
        ind[ind==0] = 1 # in this case will get normed value <0
        ind[ind==len(x)] = len(x) - 1 # in this case, will get normed value >0
        distance = (xq - x[ind - 1])/(x[ind] - x[ind - 1])
        yq = distance*(y[ind] - y[ind - 1]) + y[ind - 1]
        return ma.masked_array(yq, np.isnan(xq))
        # return ma.masked_array(np.interp(xq, x, y))

    def inverse(self, yq, clip=None):
        """Inverse operation of `~MidpointNorm.__call__`."""
        # Invert the above
        # x, y = [self.vmin, self._midpoint, self.vmax], [0, 0.5, 1]
        # return ma.masked_array(np.interp(yq, y, x))
        # Performs inverse operation of __call__
        x = np.array([self.vmin, self._midpoint, self.vmax])
        y = np.array([0, 0.5, 1])
        yq = np.atleast_1d(yq)
        ind = np.searchsorted(y, yq)
        ind[ind==0] = 1
        ind[ind==len(y)] = len(y) - 1
        distance = (yq - y[ind - 1])/(y[ind] - y[ind - 1])
        xq = distance*(x[ind] - x[ind - 1]) + x[ind - 1]
        return ma.masked_array(xq, np.isnan(yq))

def _read_cmap_cycle_data(filename):
    """
    Helper function that reads generalized colormap and color cycle files.
    """
    empty = (None, None, None)
    if os.path.isdir(filename): # no warning
        return empty
    # Directly read segmentdata json file
    # NOTE: This is special case! Immediately return name and cmap
    split = os.path.basename(filename).split('.')
    if len(split)==1:
        return empty
    *name, ext = split
    name = ''.join(name)
    if ext=='json':
        with open(filename, 'r') as f:
            data = json.load(f)
        N = rcParams['image.lut']
        if 'space' in data:
            space = data.pop('space')
            cmap = PerceptuallyUniformColormap(name, data, space=space, N=N)
        else:
            cmap = mcolors.LinearSegmentedColormap(name, data, N=N)
        if name[-2:]=='_r':
            cmap = cmap.reversed(name[:-2])
        return name, None, cmap
    # Read .rgb, .rgba, .xrgb, and .xrgba files
    elif ext in ('rgb', 'xrgb', 'rgba', 'xrgba'):
        # Load
        # NOTE: This appears to be biggest import time bottleneck! Increases
        # time from 0.05s to 0.2s, with numpy loadtxt or with this regex thing.
        data = [_delim.split(line.strip()) for line in open(filename).readlines()]
        try:
            data = [[float(num) for num in line] for line in data]
        except ValueError:
            warnings.warn(f'Failed to load "{filename}". Expected a table of comma or space-separated values.')
            return empty
        # Build x-coordinates and standardize shape
        data = np.array(data)
        if data.shape[1]!=len(ext):
            warnings.warn(f'Failed to load "{filename}". Got {data.shape[1]} columns, but expected {len(ext)}.')
            return empty
        if ext[0]!='x': # i.e. no x-coordinates specified explicitly
            x = np.linspace(0, 1, data.shape[0])
        else:
            x, data = data[:,0], data[:,1:]
    # Load XML files created with scivizcolor
    # Adapted from script found here: https://sciviscolor.org/matlab-matplotlib-pv44/
    elif ext=='xml':
        try:
            xmldoc = etree.parse(filename)
        except IOError:
            warnings.warn(f'Failed to load "{filename}".')
            return empty
        x, data = [], []
        for s in xmldoc.getroot().findall('.//Point'):
            # Verify keys
            if any(key not in s.attrib for key in 'xrgb'):
                warnings.warn(f'Failed to load "{filename}". Missing an x, r, g, or b specification inside one or more <Point> tags.')
                return empty
            if 'o' in s.attrib and 'a' in s.attrib:
                warnings.warn(f'Failed to load "{filename}". Contains ambiguous opacity key.')
                return empty
            # Get data
            color = []
            for key in 'rgbao': # o for opacity
                if key not in s.attrib:
                    continue
                color.append(float(s.attrib[key]))
            x.append(float(s.attrib['x']))
            data.append(color)
        # Convert to array
        if not all(len(data[0])==len(color) for color in data):
             warnings.warn(f'File {filename} has some points with alpha channel specified, some without.')
             return empty
    elif ext=='hex':
        # Read hex strings
        string = open(filename).read() # into single string
        data = re.findall('#[0-9a-fA-F]{6}', string) # list of strings
        if len(data)<2:
            warnings.warn(f'Failed to load "{filename}".')
            return empty
        # Convert to array
        x = np.linspace(0, 1, len(data))
        data = [mcolors.to_rgb(color) for color in data]
    else:
        warnings.warn(f'Colormap/cycle file "{filename}" has unknown extension.')
        return empty
    # Standardize and reverse if necessary to cmap
    x, data = np.array(x), np.array(data)
    x = (x - x.min()) / (x.max() - x.min()) # for some reason, some aren't in 0-1 range
    if (data>2).any(): # from 0-255 to 0-1
        data = data/255
    if name[-2:]=='_r':
        name = name[:-2]
        data = data[::-1,:]
        x = 1 - x[::-1]
    # Return data
    return name, x, data

def register_cmaps():
    """
    Registers colormaps packaged with ProPlot or saved to the ``~/.proplot/cmaps``
    folder. Maps are named according to their filenames -- for example,
    ``name.xyz`` will be registered as ``'name'``. Use `~proplot.demos.cmap_show`
    to generate a table of the registered colormaps

    Valid file extensions are described in the below table.

    =====================  =============================================================================================================================================================================================================
    Extension              Description
    =====================  =============================================================================================================================================================================================================
    ``.hex``               List of HEX strings in any format (comma-separated, separate lines, with double quotes... anything goes).
    ``.xml``               XML files with ``<Point .../>`` entries specifying ``x``, ``r``, ``g``, ``b``, and optionally, ``a`` values, where ``x`` is the colormap coordinate and the rest are the RGB and opacity (or "alpha") values.
    ``.rgb``               3-column table delimited by commas or consecutive spaces, each column indicating red, blue and green color values.
    ``.xrgb``              As with ``.rgb``, but with 4 columns. The first column indicates the colormap coordinate.
    ``.rgba``, ``.xrgba``  As with ``.rgb``, ``.xrgb``, but with a trailing opacity (or "alpha") column.
    =====================  =============================================================================================================================================================================================================
    """
    # Read colormaps from directories
    N = rcParams['image.lut'] # query this when register function is called
    for filename in sorted(glob.glob(os.path.join(_data_cmaps, '*'))) + \
                sorted(glob.glob(os.path.join(_data_user_cmaps, '*'))):
        name, x, data = _read_cmap_cycle_data(filename)
        if name is None:
            continue
        if isinstance(data, mcolors.LinearSegmentedColormap):
            cmap = data
        else:
            data = [(x,color) for x,color in zip(x,data)]
            cmap = mcolors.LinearSegmentedColormap.from_list(name, data, N=N)
        mcm.cmap_d[name] = cmap
        cmaps.add(name)

    # Fix the builtin rainbow colormaps by switching from Listed to
    # LinearSegmented -- don't know why matplotlib stores these as
    # discrete maps by default, dumb.
    for name in _cmap_categories['Matplotlib Originals']: # initialize as empty lists
        cmap = mcm.cmap_d.get(name, None)
        if cmap and isinstance(cmap, mcolors.ListedColormap):
            mcm.cmap_d[name] = mcolors.LinearSegmentedColormap.from_list(name, cmap.colors)

    # Reverse some included colormaps, so colors
    # go from 'cold' to 'hot'
    for name in ('Spectral',):
        mcm.cmap_d[name] = mcm.cmap_d[name].reversed()

    # Delete ugly cmaps (strong-arm user into using the better ones)
    greys = mcm.cmap_d.get('Greys', None)
    if greys is not None:
        mcm.cmap_d['Grays'] = greys
    for category in _cmap_categories_delete:
        for name in _cmap_categories:
            mcm.cmap_d.pop(name, None)

    # Add shifted versions of cyclic colormaps, and prevent same colors on ends
    for cmap in mcm.cmap_d.values():
        cmap._cyclic = (cmap.name.lower() in ('twilight', 'phase', 'graycycle'))

def register_cycles():
    """
    Registers colormaps packaged with ProPlot or saved to the ``~/.proplot/cycles``
    folder. Cycles are named according to their filenames -- for example,
    ``name.hex`` will be registered as ``'name'``. Use `~proplot.demos.cycle_show`
    to generate a table of the registered cycles.

    For valid file extensions, see `register_cmaps`.
    """
    # Read cycles from directories
    icycles = {}
    for filename in sorted(glob.glob(os.path.join(_data_cycles, '*'))) + \
                sorted(glob.glob(os.path.join(_data_user_cycles, '*'))):
        name, x, data = _read_cmap_cycle_data(filename)
        if name is None:
            continue
        if isinstance(data, mcolors.LinearSegmentedColormap):
            warnings.warn(f'Failed to load {filename} as color cycle.')
            continue
        icycles[name] = data
    for name,colors in {**_cycles_preset, **icycles}.items():
        mcm.cmap_d[name] = mcolors.ListedColormap([to_rgb(color) for color in colors], name=name)
        cycles.add(name)

    # Remove redundant or ugly ones, plus ones that are just merged existing maps
    for name in ('tab10', 'tab20', 'tab20b', 'tab20c', 'Paired', 'Pastel1', 'Pastel2', 'Dark2'):
        mcm.cmap_d.pop(name, None)

    # *Change* the name of some more useful ones
    for (name1,name2) in [('Accent','Set1')]:
        cycle = mcm.cmap_d.pop(name1, None)
        if cycle:
            mcm.cmap_d[name2] = cycle
            cycles.add(name2)

def register_colors(nmax=np.inf):
    """
    Reads full database of crowd-sourced XKCD color names and official
    Crayola color names, then filters them to be sufficiently "perceptually
    distinct" in the HCL colorspace. Use `~proplot.demos.color_show` to
    generate a table of the resulting filtered colors.
    """
    # Reset native colors dictionary and add some default groups
    # Add in CSS4 so no surprises for user, but we will not encourage this
    # usage and will omit CSS4 colors from the demo table.
    scale = (360, 100, 100)
    translate =  {'b': 'blue',    'g': 'green',  'r': 'red',   'c': 'cyan',
                  'm': 'magenta', 'y': 'yellow', 'k': 'black', 'w': 'white'}
    base = mcolors.BASE_COLORS
    full = {translate[key]:value for key,value in mcolors.BASE_COLORS.items()} # full names
    mcolors._colors_full_map.clear() # clean out!
    mcolors._colors_full_map.cache.clear() # clean out!
    for name,dict_ in (('base',base), ('full',full), ('css',mcolors.CSS4_COLORS)):
        colordict.update({name:dict_})

    # Register 'filtered' colors, and get their HSL values
    # The below order is order of preference for identical color names from
    # different groups.
    names = []
    seen = {*base, *full} # never overwrite these ones!
    hcls = np.empty((0,3))
    files = [os.path.join(_data_colors, f'{name}.txt') for name in ('opencolors', 'xkcd', 'crayola')]
    for file in files:
        category, _ = os.path.splitext(os.path.basename(file))
        data = np.genfromtxt(file, delimiter='\t', dtype=str, comments='%', usecols=(0,1)).tolist()
        # Immediately add all opencolors
        if category=='opencolors':
            dict_ = {name:color for name,color in data}
            mcolors._colors_full_map.update(dict_)
            colordict.update({'opencolors':dict_})
            continue
        # Other color dictionaries are filtered, and their names are sanitized
        i = 0
        dict_ = {}
        ihcls = []
        colordict[category] = {} # just initialize this one
        for name,color in data: # is list of name, color tuples
            if i>=nmax: # e.g. for xkcd colors
                break
            for regex,sub in _sanitize_names:
                name = re.sub(regex, sub, name)
            if name in seen or re.search(_bad_names, name):
                continue
            seen.add(name)
            names.append((category, name)) # save the category name pair
            ihcls.append(to_xyz(color, space=_distinct_colors_space))
            dict_[name] = color # save the color
            i += 1
        _colors_unfiltered[category] = dict_
        hcls = np.concatenate((hcls, ihcls), axis=0)

    # Remove colors that are 'too similar' by rounding to the nearest n units
    # WARNING: Unique axis argument requires numpy version >=1.13
    # print(f'Started with {len(names)} colors, removed {deleted} insufficiently distinct colors.')
    deleted = 0
    hcls = hcls/np.array(scale)
    hcls = np.round(hcls/_distinct_colors_threshold).astype(np.int64)
    _, index, counts = np.unique(hcls, return_index=True, return_counts=True, axis=0) # get unique rows
    counts = counts.sum()
    for i,(category,name) in enumerate(names):
        if name not in _exceptions_names and i not in index:
            deleted += 1
        else:
            colordict[category][name] = _colors_unfiltered[category][name]
    for key,kw in colordict.items():
        mcolors._colors_full_map.update(kw)

# Register stuff when this module is imported
# The 'cycles' are simply listed colormaps, and the 'cmaps' are the smoothly
# varying LinearSegmentedColormap instances or subclasses thereof
cmaps = set() # track *downloaded* colormaps; user can then check this list
"""List of new registered colormap names."""

cycles = set() # track *all* color cycles
"""List of registered color cycle names."""

_colors_unfiltered = {} # downloaded colors categorized by filename
colordict = {} # limit to 'sufficiently unique' color names
"""Filtered, registered color names by category."""

register_colors() # must be done first, so we can register OpenColor cmaps
register_cmaps()
register_cycles()
cmaps = set(sorted(cmaps))
cycles = set(sorted(cycles))

# Finally our dictionary of normalizers
# Includes some custom classes, so has to go at end
# NOTE: Make BinNorm inaccessible to users. Idea is that all other normalizers
# can be wrapped by BinNorm -- BinNorm is just used to break colors into
# discrete levels.
normalizers = {
    'none':       mcolors.NoNorm,
    'null':       mcolors.NoNorm,
    'zero':       MidpointNorm,
    'midpoint':   MidpointNorm,
    'segments':   LinearSegmentedNorm,
    'segmented':  LinearSegmentedNorm,
    'log':        mcolors.LogNorm,
    'linear':     mcolors.Normalize,
    'power':      mcolors.PowerNorm,
    'symlog':     mcolors.SymLogNorm,
    }
"""Dictionary of possible normalizers. See `Norm` for a table."""

