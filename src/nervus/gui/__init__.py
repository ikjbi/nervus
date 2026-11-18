"""The Nervus desktop editor (PySide6), organised as Model-View-Controller.

- ``models``: Qt wrappers around the core diagram and simulation results. They emit signals on change.
- ``views``: widgets and the canvas. They render the models and forward user input to controllers.
- ``controllers``: change the models (through undoable commands) and run simulations.
"""
