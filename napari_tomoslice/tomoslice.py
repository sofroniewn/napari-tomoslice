from enum import auto
from functools import partial
from typing import Optional

import mrcfile
import napari
import napari.layers
import numpy as np
from napari.utils.misc import StringEnum

from .plane_controls import shift_plane_along_normal, set_plane_normal_axis
from psygnal import Signal


class RenderingMode(StringEnum):
    VOLUME = auto()
    PLANE = auto()


class TomoSlice:
    plane_thickness_changed = Signal(float)
    rendering_mode_changed = Signal(str)

    def __init__(self, viewer: napari.Viewer):
        self.viewer = viewer
        self.viewer.dims.ndisplay = 3
        self.volume_layer: Optional[napari.layers.Image] = None
        self._rendering_mode: RenderingMode = RenderingMode.VOLUME

    @property
    def rendering_mode(self):
        return str(self._rendering_mode)

    @rendering_mode.setter
    def rendering_mode(self, value):
        self._rendering_mode = RenderingMode(value)
        self.volume_layer.experimental_slicing_plane.enabled = self._render_as_plane
        self.rendering_mode_changed.emit(self.rendering_mode)

    @property
    def _render_as_plane(self):
        if self.rendering_mode == RenderingMode.PLANE:
            return True
        else:
            return False

    @property
    def plane_thickness(self):
        return self.volume_layer.experimental_slicing_plane.thickness

    @plane_thickness.setter
    def plane_thickness(self, value):
        self.volume_layer.experimental_slicing_plane.thickness = value
        self.plane_thickness_changed.emit()

    def open_tomogram(self, tomogram_file: str):
        with mrcfile.open(tomogram_file) as mrc:
            tomogram = mrc.data
        self.add_volume_layer(tomogram)
        self.connect_callbacks()
        self.viewer.reset_view()
        self.viewer.camera.angles = (140, -55, -140)
        self.viewer.camera.zoom = 0.8

    def close_tomogram(self):
        self.disconnect_callbacks()
        self.viewer.layers.remove(self.volume_layer)

    def add_volume_layer(self, tomogram: np.ndarray):
        render_as_plane = True if self.rendering_mode == RenderingMode.PLANE else False
        plane_parameters = {
            'enabled': render_as_plane,
            'position': np.array(tomogram.shape) / 2,
            'normal': (1, 0, 0),
            'thickness': 5,
        }
        self.volume_layer = self.viewer.add_image(
            data=tomogram,
            name='tomogram',
            colormap='gray_r',
            rendering='mip',
            experimental_slicing_plane=plane_parameters,
        )

    def if_plane_enabled(self, func):
        """Decorator for conditional execution of callbacks.
        """

        def inner(*args, **kwargs):
            if self.volume_layer.experimental_slicing_plane.enabled:
                return func(*args, **kwargs)

        return inner

    def connect_callbacks(self):
        # plane click and drag
        self._mouse_drag_callback = partial(
            self.if_plane_enabled(shift_plane_along_normal),
            layer=self.volume_layer
        )
        self.viewer.mouse_drag_callbacks.append(
            self._mouse_drag_callback
        )
        # plane orientation
        for key in 'xyz':
            callback = partial(
                self.if_plane_enabled(set_plane_normal_axis),
                layer=self.volume_layer,
                axis=key
            )
            self.viewer.bind_key(key, callback)

        #
        self.volume_layer.experimental_slicing_plane.events.enabled.connect(
            partial(self.rendering_mode_changed.emit, self.rendering_mode)
        )
        self.volume_layer.experimental_slicing_plane.events.thickness.connect(
            partial(self.plane_thickness_changed.emit, self.plane_thickness)
        )

    def disconnect_callbacks(self):
        self.viewer.mouse_drag_callbacks.remove(self._mouse_drag_callback)
        for key in 'xyz':
            self.viewer.keymap.pop(key.upper())
