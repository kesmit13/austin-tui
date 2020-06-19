# This file is part of "austin-tui" which is released under GPL.
#
# See file LICENCE or go to http://www.gnu.org/licenses/ for full license
# details.
#
# austin-tui is top-like TUI for Austin.
#
# Copyright (c) 2018-2020 Gabriele N. Tornetta <phoenix1987@gmail.com>.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import curses
import sys
from typing import Any

from importlib_resources import files

from lxml.etree import (
    parse as parse_xml_stream,
    fromstring as parse_xml_string,
    QName,
    _Comment as Comment,
)

from austin_tui.view.palette import Palette
import austin_tui.widgets.catalog as catalog
from austin_tui.widgets.markup import markup


class _ClassNotFoundError(Exception):
    pass


def _find_class(class_name):
    try:
        # Try to get a class from the standard catalog
        return getattr(catalog, class_name)
    except AttributeError:
        # Try from any of the loaded modules
        for _, module in sys.modules.items():
            try:
                return getattr(module, class_name)
            except AttributeError:
                pass

    raise _ClassNotFoundError(f"Cannot find class '{class_name}'")


class ViewBuilderError(Exception):
    pass


def _issignal(node):
    return QName(node).localname == "signal"


def _ispalette(node):
    return QName(node).localname == "palette"


def _validate_ns(node):
    if QName(node).namespace != "http://austin.p403n1x87.com/ui":
        raise ViewBuilderError(f"Node '{node}' has invalid namespace")


class View:
    def __init__(self, name):
        self._widgets = {}
        self._input_event = asyncio.Event()
        self._input_task = asyncio.get_event_loop().create_task(self._input_loop())
        self._event_handlers = {}

        self._open = False

        self.name = name
        self.palette = Palette()
        self.root_widget = None

    async def _input_loop(self):
        await self._input_event.wait()
        while self._open:
            await asyncio.sleep(0.015)

            if not self.root_widget._win:
                continue

            try:
                if self._event_handlers[self.root_widget._win.getkey()]():
                    self.root_widget.refresh()
            except (KeyError, curses.error):
                pass

            except Exception as e:
                from austin_tui import write_exception_to_file

                write_exception_to_file(e)
                raise KeyboardInterrupt()

    def _build(self, node):
        _validate_ns(node)
        widget_class = QName(node).localname
        try:
            # Try to get a widget from the standard catalog
            widget = _find_class(widget_class)(**node.attrib)
        except _ClassNotFoundError as e:
            raise ViewBuilderError(f"Unknown widget: {widget_class}") from e

        widget.view = self
        setattr(self, widget.name, widget)

        return widget

    def connect(self, event, handler):
        self._event_handlers[event] = handler

    def markup(self, text: Any):
        return markup(str(text), self.palette)

    def open(self):
        self.root_widget.show()
        self.palette.init()

        self.root_widget.resize()
        self.root_widget.draw()
        self.root_widget.refresh()

        self._open = True
        self._input_event.set()

    def close(self):
        if not self._open:
            return

        self.root_widget.hide()
        self._input_task.cancel()
        self._open = False

    @property
    def is_open(self):
        return self._open


class ViewBuilder:
    @staticmethod
    def _parse(view_node):
        _validate_ns(view_node)

        view_class = QName(view_node).localname
        try:
            view = _find_class(view_class)(**view_node.attrib)
        except _ClassNotFoundError:
            raise ViewBuilderError(f"Cannot find view class '{view_class}'")

        root, *rest = view_node
        view.root_widget = view._build(root)
        view.connect("KEY_RESIZE", view.root_widget.resize)

        def add_children(widget, node):
            for child in node:
                if isinstance(child, Comment):
                    continue
                child_widget = view._build(child)
                child_widget.win = widget.win
                add_children(child_widget, child)
                widget.add_child(child_widget)

        add_children(view.root_widget, root)

        for node in rest:
            if isinstance(node, Comment):
                continue
            _validate_ns(node)
            if _issignal(node):
                event = node.attrib["key"]
                handler = node.attrib["handler"]
                try:
                    method = getattr(view, handler)
                except Exception as e:
                    raise ViewBuilderError(
                        f"View '{view.name}' of type {type(view).__name__} "
                        f"does not have signal handler '{handler}'"
                    ) from e
                node.attrib
                view.connect(event=event, handler=method)
            elif _ispalette(node):
                for color in node:
                    if isinstance(color, Comment):
                        continue
                    view.palette.add_color(**color.attrib)
            else:
                raise ViewBuilderError(f"Unknown view element: {node}")

        return view

    @staticmethod
    def from_stream(stream):
        return ViewBuilder._parse(parse_xml_stream(stream).getroot())

    @staticmethod
    def from_resource(module, resource):
        return ViewBuilder._parse(
            parse_xml_string(files(module).joinpath(resource).read_text().encode())
        )


if __name__ == "__main__":

    class AustinView(View):
        def on_quit(self, data=None):
            raise KeyboardInterrupt("Quit event")

        def on_previous_thread(self, data=None):
            title = self.title.get_text()
            self.title.set_text(title[1:] + title[0])
            self.title.refresh()

        def on_next_thread(self, data=None):
            title = self.title.get_text()
            self.title.set_text(title[-1] + title[:-1])
            self.title.refresh()

        def on_full_mode_toggled(self, data=None):
            pass

        def on_table_up(self, data=None):
            return self.table.scroll_up()

        def on_table_down(self, data=None):
            return self.table.scroll_down()

    view = ViewBuilder.from_resource("austin_tui.view", "tui.austinui")
    exc = None
    try:
        view.open()

        loop = asyncio.get_event_loop()
        loop.run_forever()
    except Exception as e:
        exc = e
    finally:
        view.close()
        if exc:
            raise exc
