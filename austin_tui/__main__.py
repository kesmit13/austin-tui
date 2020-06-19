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
import sys

from austin import AustinError
from austin.aio import AsyncAustin
from austin.cli import AustinArgumentParser, AustinCommandLineError
from austin_tui.models import AustinModel
from austin_tui.view import ViewBuilder
from austin_tui.view.austin import AustinProfileMode, AustinView


from austin_tui import catch


class AustinTUIArgumentParser(AustinArgumentParser):
    def __init__(self):
        super().__init__(name="austin-tui", full=False, alt_format=False)


class AustinTUI(AsyncAustin):
    def __init__(self):
        super().__init__()

        try:
            self._args = AustinTUIArgumentParser().parse_args()
        except AustinCommandLineError as e:
            reason, *code = e.args
            if reason:
                print(reason)
                AustinTUIArgumentParser().print_help()
            exit(code[0] if code else -1)

        self._model = AustinModel()
        self._view = ViewBuilder.from_resource("austin_tui.view", "tui.austinui")
        self._view.mode = (
            AustinProfileMode.MEMORY if self._args.memory else AustinProfileMode.TIME
        )

        self._global_stats = None

    def on_sample_received(self, sample):
        try:
            self._model.update(sample)
        except Exception as e:
            from austin_tui import write_exception_to_file

            write_exception_to_file(e)

    @catch
    def on_ready(self, austin_process, child_process, command_line):
        self._view._system_controller.set_child_process(child_process)

        self._view.open()

        self._view.pid_label.set_text("PPID" if self._args.children else "PID")
        self._view.pid.set_text(child_process.pid)

        self._view.thread_name_label.set_text(
            "{}TID".format("PID:" if self._args.children else "")
        )

        self._view.cmd_line.set_text(command_line)

    def on_terminate(self, stats):
        self._global_stats = stats
        self._view.stop()

    def run(self):
        loop = asyncio.get_event_loop()

        try:
            print("Starting the Austin TUI ...")
            loop.create_task(self.start(AustinTUIArgumentParser.to_list(self._args)))
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        self._view.close()

        try:
            self.terminate()
        except AustinError:
            pass

        for task in asyncio.Task.all_tasks():
            task.cancel()

        pending = [task for task in asyncio.Task.all_tasks() if not task.done()]
        if pending:
            done, _ = asyncio.get_event_loop().run_until_complete(asyncio.wait(pending))
            for t in done:
                try:
                    res = t.result()
                    if res:
                        print(res)
                except (AustinError, asyncio.CancelledError):
                    pass

        if self._global_stats:
            print(self._global_stats)


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    tui = AustinTUI()

    def handler(loop, context):
        tui._view.close()
        loop.stop()

        from austin_tui import write_exception_to_file

        write_exception_to_file(context["exception"])

    asyncio.get_event_loop().set_exception_handler(handler)

    tui.run()


if __name__ == "__main__":
    main()
