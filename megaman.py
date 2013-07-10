#!/usr/bin/env python
'''
MegaRaid Manager v0.5 - LSI MegaRAID Wrapper
Written and maintained by <chas@charlescorbett.com>

Parsing method adapted from Steven V.'s ArcSum for Adaptec.

Displays relevant MegaRAID CLI information in a digestable format.
Currently lacking a significant amount of error checking due to lack of testing.

Pending Rewrite
'''


### Imports
import subprocess
import traceback
import os
import glob
import sys
import getopt

megacli = '/usr/local/bin/megacli' 

def cleanUp():  # control freak
    print "Exit called."
    exit()

def localError( msg ):
    print "Exited due to error:"
    print 5*'-'
    print str(msg)
    print 5*'-'
    print "Please send this, the python version, and megacli location to Charles for review."

def cleanLogs():    # cleans up the annoying landfill megacli logs if the CLI argument is not passed to retain them
    cwd = str(os.getcwd()) + ".log"
    filelist = glob.glob("*.log")
    if 'CmdTool.log' in filelist:
        os.remove('CmdTool.log')
    if 'MegaSAS.log' in filelist:
        os.remove('MegaSAS.log')

def parseArguments():   # handle command line arguments for help and log retention
    logclean = False
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hl", ["help", "logs"])
    except:
        print str(err)
        cleanUp()
    for o, a in opts:
        if o in ("-h", "--help"):
            Usage()
        if o in ("-l", "--logs"):
            logclean = True
        else:
            assert False, "Unhandled argument."
    return logclean


def megaCall( scmd ):   # Let's wrap the megacli call
    try:
        ctlr_ret = subprocess.Popen(scmd, shell=False, stdout=subprocess.PIPE).communicate()[0].splitlines()
    
    except OSError:
        localError("MegaCLI not found! Check if it exists, add symlink to /usr/local/bin/megacli")
        cleanUp()

    except:
        print "Offending command: ", scmd
        traceback.print_exc()
        cleanUp()

    return ctlr_ret

def findControllers():
    global cmd
    count = 0

    cmd = [megacli, '-CfgDsply', '-aAll']
    for retline in megaCall(cmd):
        if 'Adapter' in retline:
            count += 1

    if count == 0:
        Error("No megaRAID controllers were detected. Exiting...")
        cleanUp()

    return count

def parseControllers( cnum ):
    global cmd
    controller = {'logical': [], 'devices': [], 'battery': 'Not Installed', 'bbu': []}
    con = "-a%s" % (cnum)

    cmd = [megacli, '-AdpAllInfo', con]
    for buffer in megaCall(cmd):
        key = buffer.split(' : ')[0].strip()
        val = buffer.split(' : ')[-1].strip()

        if key == 'Product Name':
            controller['model'] = val
        elif key == 'BBU':
            if val == 'Present':
                controller['battery'] = val
        elif key == 'Memory Size':
            controller['memory'] = val

    return controller

def parseBBU():
    global cmd
    controller = {'bbuvolt': 'n/a', 'bbutemp': 'n/a', 'bbustate': '???'}
    cmd = [megacli, '-AdpBbuCmd', '-aAll']
    for retline in megaCall(cmd):
        key = retline.split(':')[0].strip()
        val = retline.split(':')[-1].strip()
        if key == 'Voltage' and 'mV' in val:
            controller['bbuvolt'] = val
        elif key == 'Temperature' and 'C' in val:
            controller['bbutemp'] = val
        elif key == 'Battery State':
            controller['bbustate'] = val

    return controller

def parseLogical( cnum ):
    global cmd
    logical = []
    ldnum = 0
    con = "a%s" % cnum
    cmd = [megacli, '-LDInfo', '-lAll', con]

    for buffer in megaCall(cmd):
        key = buffer.split(' : ')[0].strip()
        val = buffer.split(' : ')[-1].strip()

        if key.startswith('Virtual Drive'):
            ldnum = [int(s) for s in key.split(':')[1].split() if s.isdigit()]
            vdnum = int(ldnum[0])
            logical.insert( vdnum, {'drives': [], 'id': 'vd'+str(vdnum)})
            vd = logical[vdnum]
        elif key == 'RAID Level':
            vd['type'] = 'RAID-' + val.split(',')[0].split('-')[1] # can support primary and secondary raid split. Not Implemented
        elif key.startswith('Name'):
            if val.split(':')[1].strip() == "":
                vd['name'] = 'Unknown'
            else:
                vd['name'] = val.split(':')[1].strip()
        elif key == 'State':
            if val == 'Optimal':
                vd['status'] = val
            elif val == 'Partially Degraded':
                vd['status'] = "!!Degraded!!" 
            else:
                vd['status'] = val
        elif key == 'Size':
            if 'TB' in val:
                vd['size'] = str(int(float(val[:-3]) * 1024)) # lolwat? Catubig status here.
            elif 'GB' in val:
                vd['size'] = str(val[:-3])
        elif key == 'Strip Size':
            vd['stripe'] = val
        elif key.split(':')[0].strip() == 'Current Cache Policy':
            vd['cache'] = val.split(':')[1].split(',')[0].strip()

    return logical

def parsePhys( cnum ):
    global cmd
    devices = []
    groups = 0
    cmd = [megacli, '-CfgDsply', '-aAll']

    for buffer in megaCall(cmd):
        shortkey = buffer.split(':')[0].strip()
        shortval = buffer.split(':')[-1].strip()

        if shortkey.startswith('DISK GROUP'):
            dg = shortval
        if shortkey == 'Virtual Drive':
            localvd = shortval.split(")")[0].strip()
        elif shortkey.startswith('Physical Disk'):
            devices.append( {'es': ''} )
            pd = devices[-1]
            pd['vd'] = localvd
            pd['pd'] = shortval
        elif shortkey == 'Enclosure Device ID':
            pd['es'] = shortval
        elif shortkey == 'Slot Number':
            enctmp = "%s:%s" % (pd['es'], shortval)
            pd['es'] = enctmp
        elif shortkey == 'PD Type':
            pd['type'] = shortval
        elif shortkey == 'Coerced Size':
            if 'TB' in shortval.split()[1]:
                pd['size'] = str(int(float(shortval.split()[0]) * 1024))
            elif 'GB' in shortval.split()[1]:
                pd['size'] = str(int(float(shortval.split()[0])))
        elif shortkey == 'Firmware state':
            if shortval == 'Rebuild':
                pd['rebuild'] = parseStatus( cnum, pd['es'] )
                pd['state'] = shortval.split(',')[0].strip()
            else:
                pd['state'] = shortval.split(',')[0].strip()
        elif shortkey == 'Media Type':
            pd['mtype'] = shortval
        elif shortkey == 'Drive Temperature':
            if int(shortval.split('C')[0]) >= 35:
                pd['temp'] = "!!!%s!!!" % shortval
            else:
                pd['temp'] = shortval
        elif 'S.M.A.R.T' in shortkey:
            pd['smart'] = shortval

    return devices

def parseStatus( cnum ):
    global cmd
    clump = "-PhysDrv[%s]" % (es)
    cmd = [megacli, '-PDRbld', '-ShowProg', clump, '-aAll']
    for buffer in megaCall(cmd):
        if buffer == "":
            pass
        elif buffer.startswith('Rebuild'):
            return buffer.split(',')[1].split('Completed')[1].strip()
        elif buffer.startswith('Device'):
            print 10*'='
            print "Unable to parse rebuild status or an error occured"
            print buffer
            print "Continuing without..."
            return "Error"

def main():
    logClean = parseArguments()

    ### Definitions
    cmd = []
    ctlr = []
    ctlr_count = 0
    maxrebuild = 0
    ldtable = {}
    pdtable = {}
    ##

    ctlr_count = findControllers()

    for cnum in range(ctlr_count):
        print "Controllers: %s" % (cnum+1)
        try:
            ctlr.insert( cnum, parseControllers(cnum) )
            ctlr[cnum]['bbu'] = parseBBU()
            ctlr[cnum]['logical'] = parseLogical(cnum)
            ctlr[cnum]['devices'] = parsePhys(cnum)
            print
        except:
            print "Something unexpected happened..."
            print "Forward this entire output to Charles with any relevant information"
            Error(traceback.print_exc())

        for pd in ctlr[cnum]['devices']:
            for ld in ctlr[cnum]['logical']:
                if pd['vd'] == ld['id'].split("vd")[1] and not pd['es'] is '': # weird fix fo weird problem
                    pd['unit'] = ld['id']   # I know this is weird, just bear with me...

    for dev in ctlr[cnum]['devices']:
        if 'rebuild' in dev and len(dev['rebuild']) > maxrebuild:
            maxrebuild = len(dev['rebuild'])

    # Lay out logical table
    ldtable = {}
    ldtable['header'] = ['Unit', 'Name', 'Type', 'Status', 'Size(GB)', 'Stripe', 'Cache']
    ldtable['width']  = [5,       12,     8,      10,       8,          8,        10]
    ldtable['key']    = ['id',   'name', 'type',  'status', 'size',     'stripe', 'cache']

    # Lay out Physical Table
    pdtable = {}
    pdtable['header'] = ['E:S', 'Type', 'Unit', 'State', '%/Time', 'Size(GB)', 'Errors', 'Temp']
    pdtable['width']  = [6,      8,      8,      8, maxrebuild+2,  10,         7,                      10]
    pdtable['key']    = ['es',  'type', 'unit', 'state', 'rebuild', 'size', 'smart', 'temp']
 
    for cnum,controller in enumerate(ctlr):
        if cnum > 0:
            print 80*'='
            print 80*'='
            print

        print
        print "Summary for controller ( %s ):" % (controller['model'])    
        print "Battery Backup: [%s @ %s @ %s] - %s" % (ctlr[0]['battery'], ctlr[cnum]['bbu']['bbuvolt'], ctlr[cnum]['bbu']['bbutemp'], ctlr[cnum]['bbu']['bbustate'])
        print

        for i in range( len(ldtable['width']) ):
            print ldtable['header'][i].ljust(ldtable['width'][i]),
        print
        print 80*'-'
        for ld in controller['logical']:
            for i in range( len(ldtable['width']) ):
                if ldtable['key'][i] in ld:
                    print ld[ldtable['key'][i]].ljust(ldtable['width'][i]),
                else:
                    print '  --  '.ljust(ldtable['width'][i])
            print
        print
        for i in range( len(pdtable['width']) ):
            print pdtable['header'][i].ljust(pdtable['width'][i]),
        print
        print 90*'-'
        for pd in controller['devices']:
            if not pd['es'] == '':
                for i in range( len(pdtable['width']) ):
                    if pdtable['key'][i] in pd:
                        print pd[pdtable['key'][i]].ljust(pdtable['width'][i]),
                    else:
                        print '  --  '.ljust(pdtable['width'][i]),
                print
        print
    print

    print "Notice: [E:S] does NOT indicate physical location of the drive!"


    if not logClean:
        cleanLogs()
    

if __name__ == '__main__':
    main()



















