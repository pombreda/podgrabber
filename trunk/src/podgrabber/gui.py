#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk

import gobject
import feedparser
import threading
import os

MAIN_WINDOW_WIDTH = 1200
MAIN_WINDOW_HEIGHT = 600

def threaded(f):
    def wrapper(*args):
        t = threading.Thread(target=f, args=args)
        t.start()
    return wrapper

downloadList = [("dl", "Download"), ("catchup", "Catchup"), ("no_dl", "Don't Download")]
syncColorMap = {-1: "red", 0: "white", 1: "green"}

class RssGui:
    ui = '''<ui>
    <toolbar name="FeedsToolbar">
      <toolitem action="AddFeed"/>
      <toolitem action="RemoveFeed"/>
      <toolitem action="EditFeed"/>
      <toolitem action="Config"/>
      <!--
      <toolitem action="Sync"/>
      -->
      <toolitem action="Quit"/>
      <separator/>
    </toolbar>
    <toolbar name="DownloadToolbar">
      <toolitem action="RefreshDownloads"/>
      <toolitem action="DownloadAll"/>
      <toolitem action="DownloadSelected"/>
      <toolitem action="MarkAsDownloaded"/>
      <toolitem action="Config"/>
      <!--
      <toolitem action="Sync"/>
      -->
      <toolitem action="Quit"/>
      <separator/>
    </toolbar>
    <toolbar name="SyncToolbar">
      <toolitem action="DeleteDownloadedFile"/>
      <toolitem action="Config"/>
      <toolitem action="RefreshSync"/>
      <toolitem action="Sync"/>
      <toolitem action="Quit"/>
      <separator/>
    </toolbar>
    </ui>'''

    def __init__(self, controller, config):

        self.controller = controller
        self.config = config

        ##create main window
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_default_size(MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT)

        ###main window handlers
        #self.window.connect("delete_event", self.delete_event)

        ###create a UIManager instance
        self.uimanager = gtk.UIManager()

        #add the accelerator group to the toplevel window
        self.accelgroup = self.uimanager.get_accel_group()
        self.window.add_accel_group(self.accelgroup)

        #create ActionGroups
        self.config_actiongroup = gtk.ActionGroup('ConfigActionGroup')
        self.download_actiongroup = gtk.ActionGroup('DownloadActionGroup')
        self.sync_actiongroup = gtk.ActionGroup('SyncActionGroup')

        #add action groups to the uimanager
        self.uimanager.insert_action_group(self.config_actiongroup, -1)
        self.uimanager.insert_action_group(self.download_actiongroup, -1)
        self.uimanager.insert_action_group(self.sync_actiongroup, -1)
#add a UI description
        self.uimanager.add_ui_from_string(self.ui)

        ##add actions
        self.config_actiongroup.add_actions(
            [
                ('Quit', gtk.STOCK_QUIT, '_Quit', None, 'Quit the Program', self.Quit),
                ('Config', gtk.STOCK_PREFERENCES, 'Configuration', None, 'Application Configuration', self.Configure),
                ('AddFeed', gtk.STOCK_ADD, 'Add Feed', None, 'Add a new RSS feed', self.AddFeed),
                ('EditFeed', gtk.STOCK_EDIT, 'Edit Feed', None, 'Edit an RSS feed', self.EditFeed),
                ('RemoveFeed', gtk.STOCK_REMOVE, 'Remove Feed', None, 'Remove an RSS feed', self.RemoveFeed),
            ]
        )
        self.download_actiongroup.add_actions(
            [
                ('RefreshDownloads', gtk.STOCK_REFRESH, 'Refresh Downloads', None, 'Refresh List of Available Downloads', self.RefreshDownloads),
                ('DownloadAll', gtk.STOCK_GOTO_BOTTOM, 'Download All', None, 'Download all Available Podcasts', self.DownloadAll),
                ('DownloadSelected', gtk.STOCK_GO_DOWN, 'Download Selected', None, 'Download Selected Available Podcasts', self.DownloadSelected),
                ('MarkAsDownloaded', gtk.STOCK_APPLY, 'Mark as Downloaded', None, 'Mark Selected Podcast as Downloaded', self.MarkAsDownloaded),
            ]
        )

        self.sync_actiongroup.add_actions(
            [
                ('DeleteDownloadedFile', gtk.STOCK_REMOVE, 'Delete', None, 'Delete Downloaded File', self.DeleteDownloadedFile),
                ('Sync', gtk.STOCK_CONNECT, 'Sync', None, 'Sync Files with Portable Media Player', self.SyncFiles),
                ('RefreshSync', gtk.STOCK_REFRESH, 'Refresh', None, 'Refresh View of Files on Local Drive and Portable Media Player', self.RefreshSync),
            ]
        )


        ##FEEDS TAB
        ##create main container for feeds tab
        self.feeds_vbox = gtk.VBox()
        self.feeds_toolbar = self.uimanager.get_widget("/FeedsToolbar")
        self.feeds_vbox.pack_start(self.feeds_toolbar, False)

        feeds_scrolled_window = gtk.ScrolledWindow()
        self.feedView = gtk.TreeView()
        feeds_scrolled_window.add(self.feedView)
        self.AddColumn(self.feedView, "Podcast", 0)
        self.feedList = gtk.ListStore(str, str, str)
        for feed_url in self.config.Feeds:
            feed_dict = self.config.Feeds[feed_url]
            podcast_name = feed_dict.get("name", "")
            download = feed_dict.get("mode", "dl")
            self.feedList.append([podcast_name, feed_url, download])

        #Attache the model to the treeView
        self.feedView.set_model(self.feedList)	
        self.feeds_status_bar = gtk.Statusbar()
        self.feeds_vbox.pack_end(self.feeds_status_bar, False)
        self.feeds_vbox.pack_start(feeds_scrolled_window, True)
        ##END FEEDS TAB


        ##DOWNLOAD TAB
        self.download_vbox = gtk.VBox()
        self.download_toolbar = self.uimanager.get_widget("/DownloadToolbar")
        self.download_vbox.pack_start(self.download_toolbar, False)

        download_scrolled_window = gtk.ScrolledWindow()
        self.downloadView = gtk.TreeView()
        download_scrolled_window.add(self.downloadView)

        for column, title in enumerate(("Feed", "URL", "Length", "File Type", "DownloadStatus")):
            self.AddColumn(self.downloadView, title, column)

        self.downloadList = gtk.ListStore(str, str, int, str, str, str, str)
        self.downloadView.set_model(self.downloadList)
        downloadViewSelection = self.downloadView.get_selection()
        downloadViewSelection.set_mode(gtk.SELECTION_MULTIPLE)

        self.download_status_bar = gtk.Statusbar()
        self.download_vbox.pack_end(self.download_status_bar, False)
        self.download_vbox.pack_start(download_scrolled_window, True)
        ##END DOWNLOAD TAB

        ###SYNC TAB
        self.sync_vbox = gtk.VBox()
        self.sync_hpaned = gtk.HPaned()

        downloaded_scrolled_window = gtk.ScrolledWindow()
        self.sync_hpaned.pack1(downloaded_scrolled_window)

        player_scrolled_window = gtk.ScrolledWindow()
        self.sync_hpaned.pack2(player_scrolled_window)

        self.sync_toolbar = self.uimanager.get_widget("/SyncToolbar")
        self.sync_vbox.pack_start(self.sync_toolbar, False)

        self.sync_status_bar = gtk.Statusbar()
        self.sync_vbox.pack_end(self.sync_status_bar, False)

        self.sync_hpaned.set_position(MAIN_WINDOW_WIDTH/2)

        self.sync_vbox.pack_start(self.sync_hpaned, True)



        self.downloadedSyncView = gtk.TreeView()
        downloaded_scrolled_window.add(self.downloadedSyncView)
        downloadRenderer = gtk.CellRendererText()
        for column, title in enumerate(("Downloaded File", "Feed", "Date", "Size")):
            #self.AddColumn(self.downloadedSyncView, title, column)
            self.downloadedSyncView.append_column(gtk.TreeViewColumn(title, downloadRenderer,
                text=column, background=4))
        self.downloadedSyncList = gtk.ListStore(str, str, str, int, str)
        self.downloadedSyncView.set_model(self.downloadedSyncList)
        downloadedSyncViewSelection = self.downloadedSyncView.get_selection()
        downloadedSyncViewSelection.set_mode(gtk.SELECTION_MULTIPLE)

        self.playerSyncView = gtk.TreeView()
        player_scrolled_window.add(self.playerSyncView)
        syncRenderer = gtk.CellRendererText()

        #for column, title in enumerate(("Portable Audio File", "Feed", "Date", "Size")):
        #    self.AddColumn(self.playerSyncView, title, column)

        for column, title in enumerate(("Portable Audio File", "Feed", "Date", "Size")):
            #self.AddColumn(self.downloadedSyncView, title, column)
            self.playerSyncView.append_column(gtk.TreeViewColumn(title, syncRenderer,
                text=column, background=4))

        self.playerSyncList = gtk.ListStore(str, str, str, int, str)
        self.playerSyncView.set_model(self.playerSyncList)
        #playerSyncViewSelection = self.playerSyncView.get_selection()
        #playerSyncViewSelection.set_mode(gtk.SELECTION_MULTIPLE)



        ###self.downloadList.append([feed_name, dl_url, length, file_type, "", mode, title])

        ###END SYNC TAB



        ###ATTACH VBOXES TO NOTEBOOK
        self.main_notebook = gtk.Notebook()
        self.main_notebook.append_page(self.feeds_vbox, gtk.Label("Feeds"))
        self.main_notebook.append_page(self.download_vbox, gtk.Label("Download"))
        self.main_notebook.append_page(self.sync_vbox, gtk.Label("Sync"))


        self.window.add(self.main_notebook)

        icon = self.window.render_icon(gtk.STOCK_EXECUTE, gtk.ICON_SIZE_BUTTON)
        self.window.set_icon(icon)

        self.window.connect("destroy", self.destroy)

        self.window.show_all()

    def updateConfig(self):
        feedDict = {}
        for feed in [list(l) for l in list(self.feedList)]:
            feedDict[feed[1]] = {"name": feed[0], "mode": feed[2]}
        self.config.Feeds = feedDict

    def Quit(self, b):
        print 'Quit'
        gtk.main_quit()

    def destroy(self, widget, data=None):
        gtk.main_quit()

    def run(self):
        # All PyGTK applications must have a gtk.main(). Control ends here
        # and waits for an event to occur (like a key press or mouse event).
        gtk.gdk.threads_init()
        try:
            gtk.main()
        except KeyboardInterrupt:
            pass


    def AddColumn(self, tree_view, title, columnId):
        column = gtk.TreeViewColumn(title, gtk.CellRendererText() , text=columnId)
        column.set_resizable(True)		
        column.set_sort_column_id(columnId)
        tree_view.append_column(column)

    def Configure(self, widget):
        print "Configure"
        conf = Config(self.config)
        result, update_dict = conf.run()
        if result == gtk.BUTTONS_OK:
            admin_config = self.config.Admin
            admin_config.update(update_dict)
            self.config.Admin = admin_config
            self.controller.update_dl_manager_max(update_dict.get("max_simultaneous_dls", 3))
            print result, update_dict
            #self.feedList.append(l)
            #self.updateConfig()

    def AddFeed(self, widget):
        print "Add Feed"
        feed = Feed()
        result_code, nfo = feed.run()
        print result_code, nfo
        #return
        if result_code == gtk.BUTTONS_OK:
            #l[2] = downloadList[l[2]][1]
            self.feedList.append(nfo)
            self.updateConfig()

    def EditFeed(self, widget, ndx=None, treeColumn=None):
        print "Edit Feed"
        #return
        selection = self.feedView.get_selection()
        treeModel, treeRows = selection.get_selected_rows()
        treeItems = [treeModel[i] for i in treeRows]
        for treeItem in treeItems:
            feed = Feed(*list(treeItem))
            result, l = feed.run()
            print result, l
            if result == gtk.BUTTONS_OK:
                treeItem[0] = l[0]
                treeItem[1] = l[1]
                treeItem[2] = l[2]
                self.updateConfig()
                #treeItem[2] = downloadList[l[2]][1]
    def RemoveFeed(self, widget):
        print "Remove Feed"
        #return
        selection = self.feedView.get_selection()
        treeModel, treeIter = selection.get_selected()
        if treeIter:
            dlg = gtk.MessageDialog(type=gtk.MESSAGE_QUESTION, buttons=gtk.BUTTONS_YES_NO, message_format="Delete feed?")
            result = dlg.run()
            print result
            if result == gtk.RESPONSE_YES:
                treeModel.remove(treeIter)
                self.updateConfig()
            dlg.destroy()


    def OnFeedViewButtonPress(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor( path, col, 0)
                self.feedViewPopup.popup( None, None, None, event.button, time)
            return 1

    def OnDownloadViewButtonPress(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                #treeview.grab_focus()
                #treeview.set_cursor( path, col, 0)
                self.downloadViewPopup.popup( None, None, None, event.button, time)
            return 1

    @threaded
    def RefreshDownloads(self, widget):
        print "RefreshDownloads"
        gtk.threads_enter()
        #status_bar = self.wTree.get_widget("mainStatusbar")
        self.downloadList.clear()
        gtk.threads_leave()
        for feed_url in self.controller.get_available_feeds():
            feed_name = self.config.Feeds[feed_url]["name"]
            mode = self.config.Feeds[feed_url]["mode"]
            gtk.threads_enter()
            self.download_status_bar.push(1, feed_name)
            gtk.threads_leave()
            for download in self.controller.get_download_list(feed_url):
                dl_url = download["enclosure"].attrib.get("url", "NONE")
                try:
                    length = int(download["enclosure"].attrib.get("length", "0"))
                except ValueError:
                    length = 0
                file_type = download["enclosure"].attrib.get("type", "UNKNOWN")
                title = download.get("title", "No Title")
                gtk.threads_enter()
                self.downloadList.append([feed_name, dl_url, length, file_type, "", mode, title])
                gtk.threads_leave()
            gtk.threads_enter()
            self.download_status_bar.push(1, "%s - Done" % feed_name)
            gtk.threads_leave()
        print "Done RefreshDownloads"

    #@threaded
    def updateDownloadStatus(self, treeIter, status):
        gtk.threads_enter()
        try:
            print "update::", status
            self.downloadList.set_value(treeIter, 4, status)
            #status_bar = self.wTree.get_widget("mainStatusbar")
            #status_bar.push(1, status)
            self.downloadView.queue_draw()
        finally:
            gtk.threads_leave()

    @threaded
    def updateDownloadStatusBar(self, statusMessage):
        gtk.threads_enter()
        try:
            self.download_status_bar.push(1, statusMessage)
        finally:
            gtk.threads_leave()

    @threaded
    def updateSyncStatusBar(self, statusMessage):
        gtk.threads_enter()
        try:
            self.sync_status_bar.push(1, statusMessage)
        finally:
            gtk.threads_leave()

    @threaded
    def DownloadAll(self, widget):
        print "DownloadAll"
        #for row in self.downloadList:
        for i, row in enumerate(self.downloadList):
            #print "row::", row
            thisIter = row.iter
            path = (i,)
            print i, row, path
            item_title = row[6]
            enclosure_url = row[1]
            mode = row[5]
            feed_name = row[0]
            #print "%s - %s - %s - %s - %s" % (item_title, enclosure_url, mode, feed_name, thisIter)
            self.controller.download_item(item_title, enclosure_url, mode, feed_name, thisIter)

    @threaded
    def DownloadSelected(self, widget):
        print "DownloadSelected"
        gtk.threads_enter()
        try:
            selection = self.downloadView.get_selection()
            treeModel, treeRows = selection.get_selected_rows()
            treeItems = [(treeModel[i], i) for i in treeRows]
        finally:
            gtk.threads_leave()
            ##pass
        for treeItem, treeIndex in treeItems:
            row = list(treeItem)
            #print "row::", row
            thisIter = treeItem.iter
            item_title = row[6]
            enclosure_url = row[1]
            mode = row[5]
            feed_name = row[0]
            self.controller.download_item(item_title, enclosure_url, mode, feed_name, thisIter)
            #print "%s - %s - %s - %s - %s" % (item_title, enclosure_url, mode, feed_name, thisIter)

    def MarkAsDownloaded(self, widget):
        print "MarkAsDownloaded"
        selection = self.downloadView.get_selection()
        treeModel, treeRows = selection.get_selected_rows()
        treeItems = [treeModel[i] for i in treeRows]
        print treeItems
        #iter_list = []
        for treeItem in treeItems:
            thisIter = treeItem.iter
            treeItemList = list(treeItem)
            self.controller.mark_as_downloaded(treeItemList[1])
            self.downloadList.remove(thisIter)

    def SyncFiles(self, widget):
        print "SyncFiles"
        self.controller.sync_files()
        self.RefreshSync(None)

    def RefreshSync(self, widget):
        print "RefreshSync"
        self.downloadedSyncList.clear()
        self.playerSyncList.clear()
        dl_files, pa_files = self.controller.get_sync_files()
        for feed, dl_file, status in dl_files:
            self.downloadedSyncList.append([dl_file, feed, str(status), 0, syncColorMap[status]])
        for feed, pa_file, status in pa_files:
            self.playerSyncList.append([pa_file, feed, str(status), 0, syncColorMap[status]])
            

    def DeleteDownloadedFile(self, widget):
        print "DeleteDownloadedFile"
        selection = self.downloadedSyncView.get_selection()
        treeModel, treeRows = selection.get_selected_rows()
        treeItems = [treeModel[i] for i in treeRows]
        for treeItem in treeItems:
            row = list(treeItem)
            print row
            filename = row[0]
            feed = row[1]
            try:
                os.unlink(os.path.join(self.config.Admin.get("download_dir", "/"), feed, filename))
            except OSError:
                print "could not delete file %s from feed %s" % (filename, feed)
        self.RefreshSync(None)
            
            
            
        #print treeItems
        #print [dir(i) for i in treeItems]
        #print [i.iter for i in treeItems]
        #print [i.path for i in treeItems]
        #print [i.model for i in treeItems]

class Feed:
    def __init__(self, name="", url="", dl=""):
			
        self.podcastNameWidget = gtk.Entry()
        self.podcastNameWidget.set_text(name)
        self.podcastUrlWidget = gtk.Entry()
        self.podcastUrlWidget.set_text(url)
        self.podcastDlWidget = gtk.combo_box_new_text()
        for dl in downloadList:
            self.podcastDlWidget.append_text(dl[0])
        try:
            dl_index = [i[0] for i in downloadList].index(dl)
        except ValueError:
            dl_index = 0
        self.podcastDlWidget.set_active(dl_index)

        self.dlg = gtk.Dialog()
        self.dlg.add_button(gtk.STOCK_OK, gtk.BUTTONS_OK)
        self.dlg.add_button(gtk.STOCK_CANCEL, gtk.BUTTONS_CANCEL)

        table = gtk.Table(3,2)

        table.attach(gtk.Label("Podcast Name"), 0, 1, 0, 1)
        table.attach(self.podcastNameWidget, 1, 2, 0, 1)
        table.attach(gtk.Label("Podcast Url"), 0, 1, 1, 2)
        table.attach(self.podcastUrlWidget, 1, 2, 1, 2)
        table.attach(gtk.Label("DL Mode"), 0, 1, 2, 3)
        table.attach(self.podcastDlWidget, 1, 2, 2, 3)

        table.show_all()
        self.dlg.vbox.add(table)
		
    def run(self):
        result = self.dlg.run()
        podcastName = self.podcastNameWidget.get_text()
        podcastUrl = self.podcastUrlWidget.get_text()
        podcastDl = self.podcastDlWidget.get_active_text()
        self.dlg.destroy()
        return result, [podcastName, podcastUrl, podcastDl]

    def OnCheckUrl(self, entry, event):
        podcastUrl = self.podcastUrlWidget.get_text()
        podcastName = self.podcastNameWidget.get_text()
        if podcastName:
            return
        if podcastUrl:
            try:
                feed = feedparser.parse(podcastUrl).get("feed", {})
                title = feed.get("title", "")
                if title:
                    self.podcastNameWidget.set_text(title)
            except:
                pass

class Config:
    def __init__(self, config):
			
        self.config = config

        self.downloadDirWidget = gtk.Entry()
        self.downloadDirWidget.set_text(self.config.Admin.get("download_dir", "/"))

        self.proxyActiveWidget = gtk.CheckButton()
        #self.proxyActiveWidget.active = self.config.Admin.get("proxy_active", False)
        #self.proxyActiveWidget.active = True
        self.proxyActiveWidget.set_active(self.config.Admin.get("proxy_active", False))

        self.proxyAddressWidget = gtk.Entry()
        self.proxyAddressWidget.set_text(self.config.Admin.get("proxy", {}).get("http", ""))

        self.max_simultaneous_dls = gtk.Entry()
        self.max_simultaneous_dls.set_text(str(self.config.Admin.get("max_simultaneous_dls", 5)))

        self.portableMediaMount = gtk.Entry()
        self.portableMediaMount.set_text(self.config.Admin.get("portable_media_mount"))

        self.dlg = gtk.Dialog()
        self.dlg.add_button(gtk.STOCK_OK, gtk.BUTTONS_OK)
        self.dlg.add_button(gtk.STOCK_CANCEL, gtk.BUTTONS_CANCEL)

        table = gtk.Table(3,2)

        table.attach(gtk.Label("Download Directory"), 0, 1, 0, 1)
        table.attach(self.downloadDirWidget, 1, 2, 0, 1)

        table.attach(gtk.Label("Proxy Active"), 0, 1, 1, 2)
        table.attach(self.proxyActiveWidget, 1, 2, 1, 2)

        table.attach(gtk.Label("Proxy Address"), 0, 1, 2, 3)
        table.attach(self.proxyAddressWidget, 1, 2, 2, 3)

        table.attach(gtk.Label("Maximum Simultaneous Downloads"), 0, 1, 3, 4)
        table.attach(self.max_simultaneous_dls, 1, 2, 3, 4)

        table.attach(gtk.Label("Portable Media Mount"), 0, 1, 4, 5)
        table.attach(self.portableMediaMount, 1, 2, 4, 5)

        table.show_all()
        self.dlg.vbox.add(table)

		
    def run(self):
        result = self.dlg.run()
        self.dlg.destroy()
        update_dict = {
            "proxy": {"http": self.proxyAddressWidget.get_text()},
            "download_dir": self.downloadDirWidget.get_text(),
            "proxy_active": self.proxyActiveWidget.get_active(),
            "max_simultaneous_dls": int(self.max_simultaneous_dls.get_text()),
            "portable_media_mount": self.portableMediaMount.get_text(),
        }
        return result, update_dict

if __name__ == "__main__":
    import rss_get
    config = rss_get.Config()
    rss_gui = RssGui(None, config)
    rss_gui.run()

