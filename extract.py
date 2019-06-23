﻿#!/usr/bin/env python

import optparse
import os
import sys
import tempfile
import datetime
from xml.etree import ElementTree as etree

from convert import read_messages, read_calls
import yaffs

def read_chunk(fd, size):
    s = fd.read(size)
    if len(s) > 0 and len(s) != size:
        raise IOError("Broken image file")
    return s

def read_segment(fd):
    chunk_data = read_chunk(fd, yaffs.CHUNK_SIZE)
    spare_data = read_chunk(fd, yaffs.SPARE_SIZE)
    if len(chunk_data) == 0 and len(spare_data) == 0:
        return None, None
    elif len(chunk_data) == 0 or len(spare_data) == 0:
        raise IOError("Broken image file")
    return chunk_data, yaffs.PackedTags2.from_buffer_copy(spare_data)

def extract(filename):
    fd = open(filename, "rb")
    yaffs_objects = {yaffs.OBJECTID_ROOT: "."}

    while True:
        chunk_data, tags = read_segment(fd)
        if chunk_data is None:
            break

        if tags.t.byteCount == 0xffff:
            header = yaffs.ObjectHeader.from_buffer_copy(chunk_data)
            full_path_name = os.path.join(yaffs_objects[header.parentObjectId], header.name)
            yaffs_objects[tags.t.objectId] = full_path_name

            if header.type == yaffs.FILE:
                remaining = header.fileSize
                out = open(full_path_name, "wb")
                try:
                    os.fchmod(out.fileno(), header.yst_mode)
                except:
                    pass

                while remaining > 0:
                    chunk_data, tags = read_segment(fd)
                    if remaining < tags.t.byteCount:
                        s = chunk_data[:remaining]
                    else:
                        s = chunk_data[:tags.t.byteCount]
                    out.write(s)
                    remaining -= len(s)
                print ("wrote", full_path_name)
            elif header.type == yaffs.SYMLINK:
                os.symlink(header.alias, full_path_name)
                print ("symlink %s -> %s" % (header.alias, full_path_name))
            elif header.type == yaffs.DIRECTORY:
                try:
                    os.mkdir(full_path_name, 0o777)
                    print ("created directory %s" % full_path_name)
                except OSError as exc:
                    if "exists" in str(exc):
                        pass
                    else:
                        print (str(exc))
                        raise
            elif header.type == yaffs.HARDLINK:
                os.link(yaffs_objects[header.equivalentObjectId], full_path_name)
                print ("hardlink %s -> %s" % (yaffs_objects[header.equivalentObjectId], full_path_name))
            else:
                print ("skipping unknown object")
                

def get_files(filename, filenames, callback=None):
    fd = open(filename, "rb")
    yaffs_objects = {yaffs.OBJECTID_ROOT: "."}

    rc = {}

    while True:
        chunk_data, tags = read_segment(fd)
        if chunk_data is None:
            break

        if tags.t.byteCount == 0xffff:
            header = yaffs.ObjectHeader.from_buffer_copy(chunk_data)
            full_path_name = os.path.join(yaffs_objects[header.parentObjectId], header.name)
            yaffs_objects[tags.t.objectId] = full_path_name
            if callback is not None:
                callback(header)

            if header.type == yaffs.FILE:
                remaining = header.fileSize
                contents = ""
                if header.name in filenames:
                    while remaining > 0:
                        chunk_data, tags = read_segment(fd)
                        if remaining < tags.t.byteCount:
                            s = chunk_data[:remaining]
                        else:
                            s = chunk_data[:tags.t.byteCount]
                        contents += s
                        remaining -= len(s)

                    rc[full_path_name] = contents
                else:
                    blocks = (remaining + yaffs.CHUNK_SIZE - 1) / yaffs.CHUNK_SIZE
                    fd.seek(blocks*(yaffs.CHUNK_SIZE+yaffs.SPARE_SIZE), 1)
                
    return rc

def dotty(header):
    if header.name.endswith(".db"):
        sys.stdout.write("+")
    else:
        sys.stdout.write(".")
    sys.stdout.flush()

def get_save_filename(filename=""):
    while True:
        if filename == "":
            new_filename = input("Save as: ")
        else:
            new_filename = input("Save as (empty=%s): " % filename)
        if new_filename == "" and filename == "":
            continue
        if new_filename != "":
            filename = new_filename
        try:
            os.stat(filename)
            ans = input("Warning: %s already exists, overwrite (y/n)? " % filename)

            if ans.lower().startswith("y"):
                break
        except OSError:
            break
    return filename

def save(filename, content):
    open(get_save_filename(filename), "wb").write(content)

def extract_sms(content):
    fd_n, name = tempfile.mkstemp()
    fd = os.fdopen(fd_n, "wb")
    try:
        fd.write(content)
        fd.close()
        messages = read_messages(name)
        print ("Read %s messages" % str(messages.attrib["count"]))
        newest = datetime.datetime.fromtimestamp(int(messages.getchildren()[0].attrib["date"])/1000)
        output = newest.strftime("sms-%Y%m%d%H%M%S.xml")
        etree.ElementTree(messages).write(get_save_filename(output), encoding="utf-8", xml_declaration=True)
        
    except Exception as exc:
        print ("Failed to extract messages: %s" % exc)
        print (repr(exc))
    finally:
        try:
            os.unlink(name)
        except:
            print ("Warning: failed to remove temporary file %s" % name)

def extract_calls(content):
    fd, name = tempfile.mkstemp()
    fd = os.fdopen(fd, "wb")
    try:
        fd.write(content)
        fd.close()
        calls = read_calls(name)
        print ("Read %s calls" % str(calls.attrib["count"]))
        newest = datetime.datetime.fromtimestamp(int(calls.getchildren()[0].attrib["date"])/1000)
        output = newest.strftime("calls-%Y%m%d%H%M%S.xml")
        etree.ElementTree(calls).write(get_save_filename(output),
                                       encoding="utf-8",
                                       xml_declaration=True)

    except Exception as exc:
        print ("Failed to extract calls: %s" % exc)
    finally:
        try:
            os.unlink(name)
        except:
            print ("Warning: failed to remove temporary file %s" % name)

def interactive(filename):
    print ("Scanning and reading image (this may take some time)")
    r = get_files(filename, ["mmssms.db", "contacts2.db"], dotty)
    print ("")
    while True:
        print ()
        print ("Found files:")
        names = r.keys()
        for i, n in enumerate(names):
            print ("[%d] %s" % (i+1, n))

        n = int(raw_input("Enter file number to extract (0 to quit): ")) - 1
        if n < 0 or n >= len(names):
            break
        name = names[n]
        print ("File %s selected." % name)
        print ("Possible actions:")
        print ("[f] save file")
        print ("[s] extract SMS messages from file")
        print ("[c] extract Call logs from file")
        t = input("Please choose action: ")
        t = t.lower()
        
        if t.startswith("f"):
            save(os.path.basename(names[n]), r[names[n]])
        elif t.startswith("s"):
            extract_sms(r[names[n]])
        elif t.startswith("c"):
            extract_calls(r[names[n]])
    

def main():
    parser = optparse.OptionParser(usage="%prog [options...] data.img")
    parser.add_option("-x", "--extract", action="store_true",
                      help="Don't search for required databases, just extract the filesystem")
    parser.add_option("-s", "--sms", action="store_true",
                      help="Input file is mmssms.db, just convert SMS messages to XML format.")
    parser.add_option("-c", "--calls", action="store_true",
                      help="Input file is contacts2.db, just convert Call Logs to XML format.")
    parser.description = "This program can extract YAFFS filesystem images, extract and convert to readable format SMS messages from mmssms.db and extract and convert to readable format Call Logs from contacts2.db. It is intended to be used with Android SMS/Call Logs Backup and Restore applications by Ritesh Sahu (android market download links: http://goo.gl/ZO5cy and http://goo.gl/MOKKJ)"
    opts, args = parser.parse_args()

    if len(args) != 1:
        parser.print_help()
        sys.exit(1)

    if opts.sms:
        try:
            extract_sms(open(args[0], "rb").read())
        except Exception as exc:
            print ("Failed to extract messages: %s" % exc)
        return

    if opts.calls:
        try:
            extract_calls(open(args[0], "rb").read())
        except Exception as exc:
            print ("Failed to extract call logs: %s" % exc)
        return

    if opts.extract:
        extract(args[0])
    else:
        interactive(args[0])

if __name__ == '__main__':
    main()
