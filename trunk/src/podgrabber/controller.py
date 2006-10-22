#!/usr/bin/env python
"""
Podcast grabber

Syntax:

    rss_get.py

"""

#import feedparser
import sys
from elementtree import ElementTree
import urllib
import threading
from sets import Set
import os
import time
import re
import xml.parsers.expat
import bsddb
import yaml
#import rss_view ##looks like this was using glade which is deprecated
import podgrabber.gui
import shutil

READ_CHUNK = 8 * 1024
attach_re = re.compile('''^attachment;\s*filename\s*=\s*['"](.*?)['"]''')


def threaded(f):
    def wrapper(*args):
        t = threading.Thread(target=f, args=args)
        t.start()
    return wrapper

class Config(object):
    def __init__(self, config_file=os.path.join(os.environ.get("HOME"), ".podgrabber", "config.yaml")):
        self.config_file = config_file
        try:
            config = yaml.load(open(self.config_file, "r"))
        except IOError:
            home_dir = os.environ.get("HOME")
            config = {
                "admin": {
                    "download_dir": os.path.join(home_dir, "podcasts"),
                    "podcast_dir": os.path.join(home_dir, ".podgrabber"),
                    "podcast_db": os.path.join(home_dir, ".podgrabber", "pods.db"),
                    "filter": "dbFileFilter",
                    "proxy": {"http": "http://localhost:3128/"},
                    "proxy_active": False,
                    "view": "gui",
                    "max_simultaneous_dls": 5,
                    'portable_media_mount': '/media/SANSA E130',
                },
                'feeds': {
                    'http://leoville.tv/podcasts/dgw.xml': {'mode': 'dl', 'name': 'Daily Giz Wiz'},
                    'http://leoville.tv/podcasts/floss.xml': {'mode': 'dl', 'name': 'FLOSS Weekly'},
                    'http://leoville.tv/podcasts/itn.xml': {'mode': 'dl', 'name': 'Inside the Net'},
                    'http://leoville.tv/podcasts/sn.xml': {'mode': 'dl', 'name': 'Security Now!'},
                    'http://leoville.tv/podcasts/twit.xml': {'mode': 'dl', 'name': 'this WEEK in TECH'},
                    'http://news.com.com/html/ne/podcasts/daily_podcast.xml?tag=txt': {'mode': 'dl', 'name': 'News.com Daily'},
                    'http://news.com.com/html/ne/podcasts/security_bites.xml?tag=txt': {'mode': 'dl', 'name': 'Security Bites'},
                    'http://sploitcast.libsyn.com/rss': {'mode': 'dl', 'name': 'SploitCast'},
                    'http://www.awaretek.com/python/index.xml': {'mode': 'dl', 'name': 'Python411'},
                    'http://www.cnet.com/i/pod/cnet_buzz.xml': {'mode': 'dl', 'name': 'Buzz Out Loud from CNET'},
                    'http://www.lugradio.org/episodes.rss': {'mode': 'dl', 'name': 'LugRadio'},
                    'http://www.oreillynet.com/pub/feed/37?format=rss2': {'mode': 'dl', 'name': 'Distributing the Future'},
                    'http://www.twis.org/audio/podcast.rss': {'mode': 'dl', 'name': 'This Week in Science'},
                }
            }


            if not os.path.isdir(config['admin']['podcast_dir']):
                os.makedirs(config['admin']['podcast_dir'])
            config_file_obj = open(self.config_file, "w")
            yaml.dump(config, config_file_obj, default_flow_style=False)
            config_file_obj.close()
        self.feeds = config.get("feeds", {})
        self.admin = config.get("admin", {})

    def serialize(self):
        config = {"admin": self.admin, "feeds": self.feeds}
        config_file_obj = open(self.config_file, "w")
        yaml.dump(config, config_file_obj, default_flow_style=False)
        config_file_obj.close()

    def setFeeds(self, value):
        self.feeds = value
        self.serialize()
    def getFeeds(self):
        return self.feeds
    Feeds = property(fset=setFeeds, fget=getFeeds)
    def setAdmin(self, value):
        self.admin = value
        self.serialize()
    def getAdmin(self):
        return self.admin
    Admin = property(fset=setAdmin, fget=getAdmin)




def get_rss_item_data(item):
    """
    return a dictionary of rss item children

    this is just a convenience function to get at an item's child data,
    particularly for enclosure tags.
    """
    children = item.getchildren()
    text_dict = {}
    for child in children:
        text_dict[child.tag] = child.text
        if child.tag == "enclosure":
            text_dict['enclosure'] = child
    return text_dict

class DownloadManager:
    """
    This class currently only supports HTTP downloads.  However, given how it
    is used, it should be easy to modify it to support FTP and even bittorrent.
    This class provides a single entry point for calling code to call -
    addItem.  I had thought about either 1) creating a threadpool and a queue
    at init time and having addItem drop downloads onto the queue and letting a
    polling thread pull them off and pass them to the threadpool or using
    Twisted to do something similar.  I still may.  I think there is nearly as
    much cause to do the same thing with getting the individual RSS feeds,
    though.

    """
    def __init__(self, config, controller):
        self.config = config
        self.controller = controller
        self.dl_sema = threading.Semaphore(self.config.Admin.get("max_simultaneous_dls", 5))
    #def addItem(self, text_dict, feed_dict):
    @threaded
    def addItem(self, item_title, enclosure_url, mode, feed_name, identifier=1):
        """
        download the given item.  return when done.

        This method expects an elementtree object for an item tag which
        contains an enclosure.


        text_dict[title]
        text_dict[enclosure]
            url
        feed_dict[mode]
        feed_dict[name]
        """
        #text_dict = get_rss_item_data(new_item)
        self.dl_sema.acquire()
        try:
            proxy_dict = self.config.Admin.get("proxy", {})
            proxy_active = self.config.Admin.get("proxy_active", False)
            if mode == "no_dl":
                print "Not downloading", item_title
                return
            elif mode == "catchup":
                print "Not downloading", item_title
                self.controller.mark_as_downloaded(enclosure_url)
                return


            print "\tDownloading", item_title
            ###GENERIC HTTP DOWNLOADER
            start_time = time.time()
            if proxy_active:
                opener = urllib.FancyURLopener(proxy_dict)
            else:
                opener = urllib.FancyURLopener({})
            f = opener.open(enclosure_url)
            filename = os.path.basename(f.url)
            headers = f.headers
            for key, val in headers.items():
                #kludge to get the filename out of the MIME contents
                if (key == "content-disposition") and (val.startswith("attachment;")):
                    attach_match = attach_re.match(val)
                    if attach_match:
                        filename = attach_match.groups()[0]

            outdir = os.path.join(self.config.Admin["download_dir"], feed_name)
            try:
                os.makedirs(outdir)
            except OSError:
                pass

            out_fn = os.path.join(outdir, filename) 
            outfile = open(out_fn, "wb")
            bytes_dl = 0
            last_time = time.time()
            last_chunk = ""
            sys.stdout.write("\tEntering download loop\n")
            sys.stdout.flush()
            sys.stdout.write("\t\t")
            sys.stdout.flush()
            while 1:
                chunk = f.read(READ_CHUNK)
                if not chunk:
                    break
                bytes_dl += len(chunk)
                outfile.write(chunk)
                curr_time = time.time()
                if curr_time - last_time > 1:
                    run_time = curr_time - start_time
                    avg_kbps = (float(bytes_dl) / run_time) / 1024
                    this_chunk = "[ %-4d ] : %s KB (%0.2f avg Kbps)" % (int(curr_time - start_time), (bytes_dl / 1024), avg_kbps)
                    self.controller.update_download_status(identifier, this_chunk)
                    #sys.stdout.write("\b" * len(last_chunk))
                    #sys.stdout.flush()
                    #sys.stdout.write(this_chunk)
                    #sys.stdout.flush()
                    last_chunk = this_chunk
                    last_time = curr_time
            outfile.close()
            end_time = time.time()
            run_time = end_time - start_time
            avg_kbps = (float(bytes_dl) / run_time) / 1024
            print "\n\t\t* Done - Downloaded %s bytes in %s seconds (%s avg Kbps)" % (bytes_dl, run_time, avg_kbps)
            self.controller.update_download_status(identifier, "Done in %s seconds" % int(run_time))
            self.controller.mark_as_downloaded(enclosure_url)
        finally:
            self.dl_sema.release()

def defaultFilter(this_list, config, feed_dict):
    """
    return the passed-in-list

    This is a non-filtering filter :-)
    """
    return [get_rss_item_data(i) for i in this_list]

def commandLineFilter(this_list, config, feed_dict):
    """
    prompt the user for which items they want to download and return a list of
    what they've selected

    This cli will accept comma and hyphen separated lists of numbers of indeces
    of the files the user would like to download.
    """
    for i, item in enumerate(this_list):
        text_dict = get_rss_item_data(item)
        print "%s - [ %s ] [ %s ] [ %s ]" % (i, text_dict.get("title", "No Title"), text_dict.get("pubDate", "No Pub Date"), text_dict['enclosure'].attrib.get("url", "No URL"))
    desired_raw = raw_input("Enter a comma separated list of the files you want to download>> ")
    if desired_raw.strip() == "":
        return []
    desired_list = [s.strip() for s in desired_raw.split(",")]
    processed_list = []
    for elem in desired_list:
        if "-" in elem:
            start, end = elem.split("-")
            start = int(start.strip())
            end = int(end.strip()) + 1
            processed_list += range(start, end)
        else:
            elem = elem.strip()
            if elem:
                processed_list.append(int(elem))
    return_list = []
    for i in Set(processed_list):
        return_list.append(get_rss_item_data(this_list[i]))
    return return_list

def dbFileFilter(this_list, config, feed_dict):
    """
    return a list of files which this user has not already downloded given
    verification from their bdb file

    This function uses a bdb file to keep track of which files have been
    downloaded.
    """
    return_list = []
    db_fn = config.Admin["podcast_db"]
    
    podcast_db = bsddb.hashopen(db_fn, "c")

    for item in this_list:
        text_dict = get_rss_item_data(item)
        url = text_dict["enclosure"].get("url")
        if not podcast_db.has_key(url):
            return_list.append(text_dict)

    podcast_db.close()
    return return_list

filterDict = {
              "defaultFilter": defaultFilter,
              "commandLineFilter": commandLineFilter,
              "dbFileFilter": dbFileFilter
             }


class IView(object):
    def __init__(self, controller, config):
        self.controller = controller
        self.config = config
    def run(self):
        raise NotImplementedError


class CliView(IView):
    def run(self):
        for feed_url in self.controller.get_available_feeds():
            for download in self.controller.get_download_list(feed_url):
                #print download
                item_title = download.get("title", "No Title")
                enclosure_url = download.get("enclosure", {}).get("url", "No URL")
                mode = self.config.Feeds[feed_url].get("mode", "no_dl")
                feed_name = self.config.Feeds[feed_url].get("name", "No Name")

                #self.controller.download_item(download, self.config.Feeds[feed_url])
                self.controller.download_item(item_title, enclosure_url, mode, feed_name)

viewDict = {
              "cli": CliView,
              #"gui": rss_view.RssGui,
              "gui": podgrabber.gui.RssGui,
             }

class RSSController:
    """
    simple litte class that takes an XML file, parses it, and passes each
    item/enclosure piece to the appropriate filter and then passes the returned
    list to the download manager.  This class could easily be threaded so that
    it would download all interesting feeds simultaneously.  That could also be
    interesting to do with Twisted.

    """
    def __init__(self):
        self.config = Config()
        self.dlm = DownloadManager(self.config, self)
        self.view = viewDict.get(self.config.Admin.get("view"), CliView)(self, self.config)

    def get_available_feeds(self):
        return self.config.Feeds

    def get_download_list(self, feed_url):
        try:
            feed_dict = self.config.Feeds[feed_url]
        except KeyError:
            return []

        proxy_dict = self.config.Admin.get("proxy", {})
        proxy_active = self.config.Admin.get("proxy_active", False)
        filter_name = self.config.Admin.get("filter", "defaultFilter")
        feedFilter = filterDict.get(filter_name, defaultFilter)
        print "Using filter", filter_name, feedFilter

        feed_description = feed_dict.get("name", "None")
        print "[ %s ] : %s" % (feed_description, feed_url)

        if proxy_active:
            opener = urllib.FancyURLopener(proxy_dict)
        else:
            opener = urllib.FancyURLopener({})
        f = opener.open(feed_url)
        feed_text = f.read()
        try:
            feed_tree = ElementTree.fromstring(feed_text)
        except xml.parsers.expat.ExpatError:
            return []
        item_attrib = feed_tree.attrib
        item_list = feedFilter([i for i in feed_tree.findall("*/item") if i.findall("enclosure")], self.config, feed_dict)
        return item_list

    def update_download_status(self, identifier, status):
        self.view.updateDownloadStatus(identifier, status)

    #def download_item(self, item, feed_dict):
    def download_item(self, item_title, enclosure_url, mode, feed_name, identifier=1):
        self.dlm.addItem(item_title, enclosure_url, mode, feed_name, identifier)

    def mark_as_downloaded(self, url):
        db_fn =  self.config.Admin["podcast_db"]
        podcast_db = bsddb.hashopen(db_fn, "c")
        podcast_db[url] = "1"
        podcast_db.close()

    def update_dl_manager_max(self, max_dls):
        print "update_dl_manager_max", max_dls
        self.dlm.dl_sema = threading.Semaphore(max_dls)

    def update_download_status_bar(self, statusMessage):
        self.view.updateDownloadStatusBar(statusMessage)

    def update_sync_status_bar(self, statusMessage):
        self.view.updateSyncStatusBar(statusMessage)

    def get_sync_files(self):
        print "syncing files"
        portable_media_root = self.config.admin.get("portable_media_mount")
        download_root = self.config.admin.get("download_dir")
        on_device_files = []
        port_media_dirs = Set([d for d in os.listdir(portable_media_root) if os.path.isdir(os.path.join(portable_media_root, d))])
        download_dirs = Set([d for d in os.listdir(download_root) if os.path.isdir(os.path.join(download_root, d))])
        common_dirs = download_dirs.intersection(port_media_dirs)
        missing_dirs = download_dirs.difference(port_media_dirs)
        print "common_dirs", common_dirs
        print "missing_dirs", missing_dirs
        files_to_del = []
        files_to_add = []
        ##
        dl_files = []
        pa_files = []
        for d in common_dirs:
            download_files = Set(os.listdir(os.path.join(download_root, d)))
            port_media_files = Set(os.listdir(os.path.join(portable_media_root, d)))
            ##do files to add
            dl_files += [(d, f, 1) for f in download_files.difference(port_media_files)]
            ##do common files
            dl_files += [(d, f, 0) for f in download_files.intersection(port_media_files)]

            ##do files to delete
            pa_files += [(d, f, -1) for f in port_media_files.difference(download_files)]
            ##do common files
            pa_files += [(d, f, 0) for f in port_media_files.intersection(download_files)]
        print "*" * 40
        print "dl_files::", dl_files
        print "pa_files::", pa_files
        print "*" * 40
        dl_files.sort()
        pa_files.sort()
        return dl_files, pa_files


    def sync_files(self):
        pm_root = self.config.admin.get("portable_media_mount")
        dl_root = self.config.admin.get("download_dir")
        dl_files, pa_files = self.get_sync_files()
        for feed, pa_file, status in pa_files:
            if status == -1:
                os.unlink(os.path.join(pm_root, feed, pa_file))
                self.update_sync_status_bar("Deleting file %s" % pa_file)
        for feed, dl_file, status in dl_files:
            if status == 1:
                self.update_sync_status_bar("Copying file %s" % dl_file)
                try:
                    os.makedirs(os.path.join(pm_root, feed))
                except OSError:
                    pass
                shutil.copyfile(os.path.join(dl_root, feed, dl_file),
                    os.path.join(pm_root, feed, dl_file))
        self.update_sync_status_bar("Done with Sync")
        return

        ##XXX - the rest of this method won't get executed.
        print "syncing files"
        portable_media_root = self.config.admin.get("portable_media_mount")
        download_root = self.config.admin.get("download_dir")
        on_device_files = []
        port_media_dirs = Set([d for d in os.listdir(portable_media_root) if os.path.isdir(os.path.join(portable_media_root, d))])
        download_dirs = Set([d for d in os.listdir(download_root) if os.path.isdir(os.path.join(download_root, d))])
        print port_media_dirs, download_dirs
        common_dirs = download_dirs.intersection(port_media_dirs)
        missing_dirs = download_dirs.difference(port_media_dirs)
        print "common_dirs", common_dirs
        print "missing_dirs", missing_dirs
        files_to_del = []
        files_to_add = []
        for d in common_dirs:
            download_files = Set(os.listdir(os.path.join(download_root, d)))
            port_media_files = Set(os.listdir(os.path.join(portable_media_root, d)))
            files_to_del += [os.path.join(portable_media_root, d, f) for f in 
                port_media_files.difference(download_files)]
            files_to_add += [(os.path.join(download_root, d, f), os.path.join(portable_media_root, d, f)) 
                for f in download_files.difference(port_media_files)]

        for d in missing_dirs:
            download_files = os.listdir(os.path.join(download_root, d))
            files_to_add += [(os.path.join(download_root, d, f), os.path.join(portable_media_root, d, f))
                for f in download_files]

        print "files_to_del", files_to_del
        print "files_to_add", files_to_add

        for file_to_del in files_to_del:
            self.update_sync_status_bar("Deleting file %s" % file_to_del)
            #os.unlink(file_to_del)

        for from_file, to_file in files_to_add:
            try:
                dir_to_make = os.path.split(to_file)[0]
                print "Making dir:", dir_to_make
                os.makedirs(os.path.split(to_file)[0])
            except OSError:
                pass
            '''
            dir_to_make = os.path.split(to_file)[0]
            print "Making dir:", dir_to_make
            os.makedirs(os.path.split(to_file)[0])
            '''
            self.update_sync_status_bar("Copying file %s" % to_file)
            shutil.copyfile(from_file, to_file)
        self.update_sync_status_bar("Done with Sync")


    def run(self):
        """
        start the ball rolling....

        """
        self.view.run()



if __name__ == "__main__":
    rsscontroller = RSSController()
    rsscontroller.run()



