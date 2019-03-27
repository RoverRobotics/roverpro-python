import argparse
from distutils.version import LooseVersion
from pathlib import Path
import subprocess
import sys

import trio

from openrover import OpenRoverProtocol
from openrover.find_device import get_ftdi_device_paths
from openrover.openrover_protocol import CommandVerbs
from openrover.serial_trio import SerialTrio

BAUDRATE = 57600

SETTINGS_VERBS = list(map(CommandVerbs, [3, 4, 5, 6, 7, 8]))


def rover_command_arg_pair(arg):
    k, v = arg.split(':', 2)
    k = CommandVerbs(int(k))
    if k not in SETTINGS_VERBS: raise ValueError
    if not 0 <= int(v) <= 255: raise ValueError
    return (CommandVerbs(int(k)), int(v))


async def amain():
    parser = argparse.ArgumentParser(
        description='OpenRover companion utility to bootload robot and configure settings.')
    parser.add_argument('-p', '--port', type=str,
                        help='Which device to use. If omitted, we will search for a possible rover device',
                        metavar='port')
    parser.add_argument('-f', '--flash', type=str, help='Load the specified firmware file onto the rover',
                        metavar="path/to/firmware.hex")
    parser.add_argument('-m', '--minimumversion', type=LooseVersion, metavar='version',
                        help='Check that the rover reports at least the given version;'
                             'version may be in the form N.N.N, N.N, or N')
    parser.add_argument('-u', '--updatesettings', type=rover_command_arg_pair, metavar='k:v', nargs='+',
                        help='Send additional commands to the rover. v may be 0-255; k may be:' + ', '.join(
                            f'{s.value}={s.name}' for s in SETTINGS_VERBS
                        ))

    args = parser.parse_args()
    if not any([args.flash, args.minimumversion, args.updatesettings]):
        parser.error('No action requested (flash, minimumversion, updatesettings). Use -h to see detailed options.')

    port = args.port
    if port is None:
        print('Scanning for possible rover devices')
        ports = get_ftdi_device_paths()
        if len(ports) == 0:
            print('No devices found')
            exit(1)
        if len(ports) > 1:
            print(f'Multiple devices found: {", ".join(ports)}')
        port = ports[0]
    print(f'Using device {port}')

    if args.flash is not None:
        hexfile = Path(args.flash)
        if not hexfile.is_file():
            print(f'Could not bootload. Hex file {hexfile.absolute()} does not exist.')
            exit(1)

        async with SerialTrio(port, baudrate=BAUDRATE) as ser:
            orp = OpenRoverProtocol(ser)
            print('instructing rover to restart')
            orp.write_nowait(0, 0, 0, CommandVerbs.RESTART, 0)
            await orp.flush()

        pargs = [sys.executable, '-m', 'booty',
                 '--port', port,
                 '--baudrate', str(BAUDRATE),
                 '--hexfile', str(hexfile),
                 '--erase',
                 '--load',
                 '--verify']
        print(f'invoking bootloader: {subprocess.list2cmdline(pargs)}')
        subprocess.check_call(pargs)

        print('starting firmware')
        async with SerialTrio(port, baudrate=BAUDRATE) as ser:
            ser.write_nowait(bytes.fromhex('f701004041437f'))

    if args.minimumversion is not None:
        expected_version = args.minimumversion
        actual_version = None
        print(f'Expecting version at least {expected_version}')
        async with SerialTrio(port, baudrate=57600) as device:
            orp = OpenRoverProtocol(device)
            orp.write_nowait(0, 0, 0, CommandVerbs.GET_DATA, 40)
            with trio.fail_after(10):
                k, version = await orp.read_one()
            if k == 40:
                actual_version = version

        if actual_version is None:
            print('could not get version')
            exit(1)
        else:
            print(f'Actual version = {actual_version}')
        if LooseVersion(str(actual_version)) < expected_version:
            print('Failed!')
            exit(1)

    if args.updatesettings:
        async with SerialTrio(port, baudrate=57600) as device:
            orp = OpenRoverProtocol(device)
            orp.write_nowait(0, 0, 0, CommandVerbs.RELOAD_SETTINGS, 0)
            for k, v in args.updatesettings or ():
                orp.write_nowait(0, 0, 0, k, v)
            orp.write_nowait(0, 0, 0, CommandVerbs.COMMIT_SETTINGS, 0)
            await orp.flush()

    print('\r\n'.join([
        r'      VROOM      ',
        r'  _           _  ',
        r' /#\ ------- /#\ ',
        r' |#|  (o=o)  |#| ',
        r' \#/ ------- \#/ ',
        r'                 ',
    ]))
    exit(0)


def main():
    trio.run(amain)


if __name__ == '__main__':
    main()
