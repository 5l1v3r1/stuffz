#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#    ollydbg_runtrace_parser.py - Little module to parse a runtrace generated by OllyDbg2
#    Copyright (C) 2014 Axel "0vercl0k" Souchet - http://www.twitter.com/0vercl0k
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import sys
import timeit
from colorama import *

def display_cpu_register(name, value):
    print '%s=%.8x' % (name, value)

class RunTraceEntry(object):
    '''This is basically one line in your Runtrace'''
    def __init__(self, line):
        self.memory = None
        self.ctx = {}
        _, self.address, self.instr, tmp = line.split('\t', 3)
        _, self.address = self.address.split('.')

        # If we have two '\t', it means we have both memory referenced & the CPU context
        x = tmp.split('\t')
        ctx = x[0]
        if len(x) == 2:
            self.memory = x[0]
            ctx = x[1]

        for reg_value in ctx.split(', '):
            reg, value = reg_value.split('=')
            self.ctx[reg] = int(value, 16)

    def __str__(self):
        return '%s - %s - %s' % (
            self.address, self.instr,
            ', '.join('%s=%.8x' % (k, v) for k, v in self.ctx.iteritems())
        )

class BreakpointManager(object):
    '''Small class to handle & keep track of the breakpoints set by the user'''
    def __init__(self):
        self.id = 0
        self.addresses = {}

    def should_we_break(self, addr):
        '''Should we break ya neck or not?'''
        return addr in self.addresses.values()

    def push(self, addr):
        '''Push an address to break on'''
        if addr not in self.addresses.values():
            self.addresses[self.id](addr)

    def remove(self, addr):
        '''Remove an address from the breakpoints'''
        if addr in self.addresses:
            self.addresses.remove(addr)

class RunTrace(object):
    '''Object to manipulate easily the information available in a Runtrace'''
    def __init__(self):
        self.entries = list()

    def parse_line(self, line):
        '''Create a RunTraceEntry instance from ``line``'''
        if line.startswith('--------') or line == '\n':
            return None

        entry = RunTraceEntry(line)
        self.entries.append(entry)
        return entry


class RunTraceShell(object):
    '''This class simulates a really basic WinDbg shell -- point is to navigate
    easily and pinpoint things quickly'''
    def __init__(self, rt):
        init(autoreset = True)
        self.rt = rt
        self.cursor = 0
        self.curr_entry = self.rt.entries[self.cursor]

        # This is a basic breakpoint manager
        self.bpmgr = BreakpointManager() 

        # We keep track of the previous entry in order to be able to diff two contexts
        # & then highlight the differences
        self.prev_entry = None

        # This is used to keep track of the nested calls we are in
        # For example:
        #  1. inc eax
        #  2. call x
        #  3.  inc eax
        #  4.  call z
        #  5.    inc ebx <- At this point callstack = [2, 4]
        #  6.    ret
        #  7.  inc eax <- At this point callstack = [2]
        # This is really useful if you want to step-back over calls. For example if we are at 7., you can 'p-' & end up
        # directly on 4. ; totally ignoring what happened in the call
        self.callstack = list()
        # This list will track all the different calls encountered in the trace ;
        # this list's going to be pretty useful when back stepping, in order to have a proper callstack
        self.all_the_calls = list()

    def _diff_and_display_cpu_registers(self):
        '''Displays & highlights only the registers modified'''
        reg32 = ('eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'esp', 'ebp')

        # We generate a simple matrix in order to keep track of the possible register differences between the current & the previous context
        # The previous context can be None at the begining ; in that case we fill the matrix with 'No difference' for every registers
        diffmatrix = dict((r, self.curr_entry.ctx[r] == self.prev_entry.ctx[r]) for r in reg32) if self.prev_entry is not None else dict((r, True) for r in reg32)

        # Rendering the CPU context now
        for i, r in enumerate(reg32):
            sys.stdout.write('%s=' % r)
            if diffmatrix[r]:
                sys.stdout.write('%.8x' % self.curr_entry.ctx[r])
            # If the register ``r`` accross the two contexts has different values, we red-highlight it
            else:
                sys.stdout.write(Style.BRIGHT + Fore.RED + '%.8x' % self.curr_entry.ctx[r])

            if (i + 1) < len(reg32):
                sys.stdout.write(' ')

            # A bit like WinDbg, we want at most five registers on the same line
            if i == 5:
                sys.stdout.write('\n')

        sys.stdout.write('\n')

        # Of course, the current instruction & the cursor position
        sys.stdout.write(Style.BRIGHT + Fore.YELLOW + ('@%.8x ' % self.cursor) + Style.BRIGHT + Fore.RED + self.curr_entry.address + ' ' + Fore.GREEN + self.curr_entry.instr + '\n')

    def _get_cpu_ctx(self, args):
        '''Does exactly as ``r`` from WinDbg'''
        # ``r`` can take register names in argument, and in that case it will display only them
        if len(args) > 0:
            for arg in args:
                if arg not in self.curr_entry.ctx:
                    print arg, 'does not exist in the CPU context'
                else:
                    display_cpu_register(arg, self.curr_entry.ctx[arg])
        else:
            self._diff_and_display_cpu_registers()

    def _kill(self, z):
        '''Killin' in the name of'''
        return 'kill'

    def _get_next_entry(self, add = 1):
        '''Gets the next entry in the runtrace: forward or backward ; your call man.'''
        # Handles the End Of Trace case
        if (self.cursor + add) >= len(self.rt.entries):
            raise Exception('EOT')
        # Handles the Start Of Trace case
        if (self.cursor + add) < 0:
            raise Exception('SOT')

        # If we want to go back & the current instruction is a call, we pop the latest encountered call
        if add < 0:
            if self.curr_entry.instr.startswith('call'):
                self.callstack.pop()

            if self.curr_entry.instr.startswith('ret'):
                self.callstack.append(
                    self.all_the_calls[-1]
                )

        # Let's move forward/backward bitches
        self.prev_entry = self.rt.entries[self.cursor]
        self.cursor += add
        self.curr_entry = self.rt.entries[self.cursor]

        # Do we have a breakpoint on this address?
        if self.bpmgr.should_we_break(self.curr_entry.address):
            raise Exception('BP')

        # If we go forward..
        if add >= 0:
            # ..and the previous instruction was a ret?
            if self.prev_entry.instr.startswith('ret'):
                # In this case we pop the latest encountered call, because it means we step'd out of the last call
                self.callstack.pop()
            # If the previous instruction is a call..
            if self.prev_entry.instr.startswith('call'):
                # ..we add it to our callstack! 
                self.callstack.append(self.cursor)
                self.all_the_calls.append(self.cursor)

        return self.curr_entry

    def _stepin(self, z):
        '''Steps into calls ; equivalent of WinDbg's ``t`` command'''
        self._get_next_entry()
        self._diff_and_display_cpu_registers()

    def _stepinback(self, z):
        '''Steps back into calls ; it basically is the exact opposite of ``t``'''
        self._get_next_entry(-1)
        self._diff_and_display_cpu_registers()

    def _stepover(self, z):
        '''Steps over calls ; equivalent of WinDbg's ``p`` command'''
        # XXX: Flawed -- not necessarely the first ret encountered :/
        if self.curr_entry.instr.startswith('call'):
            state = list(self.callstack)
            print 'State: %r' % state
            while True:
                self._get_next_entry()
                if state == self.callstack:
                    print 'State init: %r, %r' % (state, self.callstack)
                    break
        else:
            self._get_next_entry()
        self._diff_and_display_cpu_registers()

    def _stepoverback(self, z):
        '''Steps back over calls ; exact opposite of ``p``'''
        # XXX: Flawed
        if self.curr_entry.instr.startswith('call'):
            while self._get_next_entry().instr.startswith('ret') == False:
                pass

    def _goto_end_func(self, z):
        '''TODO: supposed to have ``gu``'s behavior'''
        # XXX: doesn't work :))
        while self._get_next_entry().instr.startswith('ret') == False:
            pass

        self._get_next_entry()
        self._diff_and_display_cpu_registers()

    def _go(self, z):
        '''Go!'''
        while True:
            self._get_next_entry()

    def _go_back(self, z):
        '''Goin' back in time ; what a nice feeling'''
        while True:
            self._get_next_entry(-1)

    def _bp(self, z):
        '''Sets a breakpoint in the trace'''
        if len(z) != 1:
            print 'bp <addr>'
            return

        self.bpmgr.push(int(z[0], 16))

    def _k(self, z):
        '''Attempts to display a callstack as ``k`` would do'''
        for i, entry in enumerate(self.callstack):
            sys.stdout.write('#' + Style.BRIGHT + Fore.RED + ('%.2d  ' % i) + Style.BRIGHT + Fore.GREEN + ('%s - ' % self.rt.entries[entry].instr) + Style.BRIGHT + Fore.YELLOW + ('@%.8x' % entry) + '\n')
            # print '#%.2d - %s - @%.8x' % (i, , entry)

    def shell(self):
        '''Spawn a little shell-like interface to navigate easily in the runtrace,
        a bit like you would do in a debugging session'''
        cmds = {
            'r' : self._get_cpu_ctx,

            'q' : self._kill,
            'exit' : self._kill,
            'quit' : self._kill,
            'quit()' : self._kill,

            't' : self._stepin,
            't-' : self._stepinback,

            'p' : self._stepover,
            'p-' : self._stepoverback,

            'g' : self._go,
            'g-' : self._go_back,

            'bp' : self._bp,

            'k' : self._k
            # 'gu' : self._goto_end_func
        }

        self._diff_and_display_cpu_registers()
        last_cmd = None
        while True:
            cmdline = raw_input('>>> ').lower()

            cmd = cmdline.split(' ')
            extra_args = []
            if len(cmd) > 1:
                extra_args = cmd[1 : ]

            cmd = cmd[0]
            if cmd in cmds or (cmd == '' and last_cmd is not None):
                if cmd == '':
                    cmd = last_cmd

                try:
                    ret = cmds[cmd](extra_args)
                    print 'Callstack: %r' % self.callstack
                    print 'All the calls: %r' % self.all_the_calls
                    if ret == 'kill':
                        break
                except Exception, e:
                    if str(e) == 'EOT':
                        print '/!\\ You reached the end of the trace /!\\'
                        self._diff_and_display_cpu_registers()
                    elif str(e) == 'SOT':
                        print '/!\\ You reached the begining of the trace /!\\'
                        self._diff_and_display_cpu_registers()
                    elif str(e) == 'BP':
                        print 'Breakpoint '
                    else:
                        raise(e)

                if cmd != '':
                    last_cmd = cmd
            else:
                print 'Command unknown'


def Parse(filename):
    '''Parse the runtrace ``filename`` generated by OllyDbg2'''
    print '+ Populating & parsing the Runtrace..'
    x = RunTrace()
    i = 0
    with open(filename, 'r') as f:
        for line in f:
            x.parse_line(line.lower())
            i += 1

    print '+ Done parsing %d lines' % i
    return x

def main(argc, argv):
    '''All right, bring it on'''
    if argc != 2:
        return 0

    rt = Parse(argv[1])
    print '>>> Spawning the shell'
    RunTraceShell(rt).shell()
    return 1

if __name__ == '__main__':
    sys.exit(main(len(sys.argv), sys.argv))