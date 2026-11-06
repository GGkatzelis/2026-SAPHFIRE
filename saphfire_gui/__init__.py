"""Shared pieces for the SAPHFIRE desktop GUIs (PyQt6 + matplotlib), in the format of JUICE:

    theme.py             one look for every window (Fusion, forced light theme, QSS, plot fonts)
    loading_box.py       small window that says what is happening while a heavy window is built
    plot_interaction.py  mouse interaction for any matplotlib canvas (zoom, pan, reset, log menu)
    make_icon.py         makes SAPHFIRE.ico and "SAPHFIRE Logo.png" from the biomass-burning photo

A tool adds the repository root to ``sys.path`` and imports ``saphfire_gui``.
"""
