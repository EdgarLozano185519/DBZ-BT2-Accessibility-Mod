using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace BT2Desktop
{
    public sealed class MapItem
    {
        public string Key, Label, Name;
        public override string ToString() { return Label; }
    }

    public sealed class GuideForm : Form
    {
        readonly string root, dataRoot, settingsPath;
        string python = "", emulator = "", game = "";
        bool portable;
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        readonly ConcurrentQueue<string> messages = new ConcurrentQueue<string>();
        readonly Button start = new Button(), stop = new Button(), open = new Button();
        readonly TextBox status = new TextBox(), save = new TextBox(), latest = new TextBox();
        readonly TextBox history = new TextBox(), mapName = new TextBox();
        readonly CheckBox speech = new CheckBox();
        readonly ComboBox maps = new ComboBox();
        readonly Button rename = new Button(), refresh = new Button();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        Process worker;
        StreamWriter log;
        bool stopping, closing;
        DateTime stopStarted;

        public GuideForm(string workspace)
        {
            root = workspace;
            dataRoot = File.Exists(Path.Combine(root,"worker","guide-worker.exe"))
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"DBZ BT2 Guide") : root;
            Directory.CreateDirectory(dataRoot);
            settingsPath = Path.Combine(dataRoot,"desktop-settings.json");
            if(File.Exists(settingsPath)) {
                var settings = json.Deserialize<Dictionary<string,object>>(File.ReadAllText(settingsPath));
                if(settings.ContainsKey("python")) python = Convert.ToString(settings["python"]);
                if(settings.ContainsKey("emulator")) emulator = Convert.ToString(settings["emulator"]);
                if(settings.ContainsKey("game")) game = Convert.ToString(settings["game"]);
                if(settings.ContainsKey("portable")) portable = Convert.ToBoolean(settings["portable"]);
            }
            Text = "DBZ BT2 Accessibility Guide";
            AccessibleName = Text;
            Font = new Font("Segoe UI", 11);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(780,680);
            MinimumSize = new Size(700,620);
            StartPosition = FormStartPosition.CenterScreen;

            var layout = new TableLayoutPanel {
                Dock = DockStyle.Fill, Padding = new Padding(16), ColumnCount = 2, RowCount = 11
            };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,160));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            Controls.Add(layout);
            for (int i=0;i<11;i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles[6] = new RowStyle(SizeType.Percent,100);

            var buttons = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Fill, WrapContents=true };
            SetButton(start,"Start &guide","Start guide",0, delegate { StartGuide(); });
            SetButton(stop,"Sto&p guide","Stop guide",1, delegate { StopGuide(); });
            SetButton(open,"&Open game","Open game",2, delegate { OpenGame(); });
            buttons.Controls.AddRange(new Control[]{start,stop,open});
            layout.Controls.Add(buttons,0,0); layout.SetColumnSpan(buttons,2);
            stop.Enabled=false;

            SetupReadOnly(status,"Guide status",3); status.Text="Stopped";
            SetupReadOnly(save,"Current save",4);
            SetupReadOnly(latest,"Latest guide message",6);
            latest.Multiline=true; latest.Height=65; latest.Text="Open the game, then start the guide.";
            SetupReadOnly(history,"Guide message history",7);
            history.Multiline=true; history.ScrollBars=ScrollBars.Vertical;
            history.Dock=DockStyle.Fill; history.MinimumSize=new Size(200,140);
            AddRow(layout,1,"Status",status);
            AddRow(layout,2,"Current save",save);
            speech.Text="Speak guide messages (NVDA preferred)"; speech.AccessibleName="Speak guide messages, NVDA preferred with SAPI fallback";
            speech.Checked=true; speech.AutoSize=true; speech.TabIndex=5;
            layout.Controls.Add(speech,1,3);
            AddRow(layout,4,"Latest message",latest);
            var read = new Button();
            SetButton(read,"Read &latest message","Read latest message",8,
                delegate { latest.Focus(); latest.SelectAll(); });
            layout.Controls.Add(read,1,5);
            AddRow(layout,6,"Message history",history);

            maps.DropDownStyle=ComboBoxStyle.DropDownList;
            maps.Dock=DockStyle.Fill; maps.AccessibleName="Discovered maps"; maps.TabIndex=9;
            maps.SelectedIndexChanged += delegate {
                var item=maps.SelectedItem as MapItem;
                mapName.Text=item==null ? "" : item.Name;
                rename.Enabled=item!=null && worker==null;
            };
            AddRow(layout,7,"Discovered maps",maps);
            mapName.Dock=DockStyle.Fill; mapName.AccessibleName="Map name";
            mapName.MaxLength=100; mapName.TabIndex=10;
            AddRow(layout,8,"Map name",mapName);
            var mapButtons = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Fill };
            SetButton(rename,"Save map &name","Save map name",11,delegate { RenameMap(); });
            SetButton(refresh,"&Refresh maps","Refresh maps and current save",12,delegate { RefreshMaps(); });
            mapButtons.Controls.AddRange(new Control[]{rename,refresh});
            layout.Controls.Add(mapButtons,1,9);

            var footer = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Fill };
            var help = new Button(); var exit = new Button(); var configure = new Button();
            SetButton(configure,"&Settings","Settings: choose your emulator and game",13,delegate { Configure(); });
            SetButton(help,"&Help","Help and keyboard controls",13,delegate {
                MessageBox.Show(this,
                    "Use Tab and Shift+Tab to move between controls; Enter or Space activates buttons.\n\n"+
                    "Open game starts BT2 normally from its memory card. It never resumes a save state. " +
                    "Start guide enables spoken directions and tones. Stop guide silences it; the game stays open.\n\n"+
                    "While the game has focus: T or L1 requests teleport when paused; R repeats the destination; " +
                    "N and B change local or explicitly selected destinations.\n\n"+
                    "Speech uses NVDA when it is running, with SAPI as a backup. Guidance pauses while another window has focus, " +
                    "so it does not interrupt the screen reader while you use this interface.\n\n"+
                    "Map names can be changed while the guide is stopped. Return to the game with Alt+Tab. " +
                    "The status, latest message, history, map list and buttons use standard Windows controls for screen readers.",
                    "Guide help",MessageBoxButtons.OK,MessageBoxIcon.Information);
            });
            SetButton(exit,"&Close","Close guide window",14,delegate { Close(); });
            footer.Controls.AddRange(new Control[]{configure,help,exit});
            layout.Controls.Add(footer,1,10);
            AcceptButton=start;
            timer.Interval=150; timer.Tick+=delegate { DrainMessages(); }; timer.Start();
            Shown+=delegate { RefreshMaps(); if(emulator.Length==0 || game.Length==0) Configure(); start.Focus(); };
            FormClosing+=OnClosing;
        }

        static void SetButton(Button button,string text,string name,int tab,EventHandler handler)
        {
            button.Text=text; button.AccessibleName=name; button.AutoSize=true;
            button.MinimumSize=new Size(130,36); button.TabIndex=tab; button.Click+=handler;
            button.Margin=new Padding(3,3,10,5);
        }
        static void SetupReadOnly(TextBox box,string name,int tab)
        {
            box.ReadOnly=true; box.AccessibleName=name; box.TabIndex=tab;
            box.Dock=DockStyle.Fill; box.BackColor=SystemColors.Window;
        }
        static void AddRow(TableLayoutPanel layout,int row,string caption,Control control)
        {
            var label=new Label { Text=caption, AutoSize=true, Anchor=AnchorStyles.Left,
                Margin=new Padding(3,8,10,8), AccessibleName=caption };
            layout.Controls.Add(label,0,row); layout.Controls.Add(control,1,row);
            control.Margin=new Padding(3,6,3,6);
        }
        static string Quote(string path) { return "\""+path+"\""; }
        void Configure()
        {
            using(var dialog = new Form()) {
                dialog.Text="Guide settings"; dialog.AccessibleName=dialog.Text;
                dialog.Font=Font; dialog.ClientSize=new Size(800,490);
                dialog.FormBorderStyle=FormBorderStyle.FixedDialog;
                dialog.MaximizeBox=false; dialog.MinimizeBox=false;
                dialog.StartPosition=FormStartPosition.CenterParent;
                var layout=new TableLayoutPanel { Dock=DockStyle.Fill, Padding=new Padding(16), ColumnCount=3, RowCount=8 };
                layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,125));
                layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
                layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,110));
                var note=new Label { AutoSize=true, Dock=DockStyle.Fill, Text="Find PCSX2 and your BT2 dump automatically, or browse below. Open game sets up the guide connection while PCSX2 is closed. Portable and Qt builds use their own configuration and PINE port." };
                layout.Controls.Add(note,0,0); layout.SetColumnSpan(note,3);
                var emulatorBox=new TextBox { Text=emulator, AccessibleName="PCSX2 executable", Dock=DockStyle.Fill, TabIndex=0 };
                var gameBox=new TextBox { Text=game, AccessibleName="Your BT2 game dump", Dock=DockStyle.Fill, TabIndex=2 };
                layout.Controls.Add(new Label { Text="PCSX2", AutoSize=true },0,1);
                layout.Controls.Add(emulatorBox,1,1);
                layout.Controls.Add(new Label { Text="Game dump", AutoSize=true },0,2);
                layout.Controls.Add(gameBox,1,2);
                var emulatorBrowse=new Button { Text="&Browse...", AccessibleName="Browse for PCSX2", TabIndex=1, AutoSize=true };
                var gameBrowse=new Button { Text="B&rowse...", AccessibleName="Browse for your game dump", TabIndex=3, AutoSize=true };
                emulatorBrowse.Click+=delegate { using(var picker=new OpenFileDialog { Title="Choose PCSX2", Filter="Windows application (*.exe)|*.exe", CheckFileExists=true }) { if(picker.ShowDialog(dialog)==DialogResult.OK) emulatorBox.Text=picker.FileName; } };
                gameBrowse.Click+=delegate { using(var picker=new OpenFileDialog { Title="Choose your BT2 game dump", Filter="Game dumps (*.iso;*.chd;*.cso;*.gz)|*.iso;*.chd;*.cso;*.gz|All files (*.*)|*.*", CheckFileExists=true }) { if(picker.ShowDialog(dialog)==DialogResult.OK) gameBox.Text=picker.FileName; } };
                layout.Controls.Add(emulatorBrowse,2,1); layout.Controls.Add(gameBrowse,2,2);
                var mode=new CheckBox { Text="Use portable PCSX2 settings", AccessibleName="Use portable PCSX2 settings", Checked=portable, AutoSize=true };
                layout.Controls.Add(mode,1,3); layout.SetColumnSpan(mode,2);
                var emulatorChoices=new ComboBox { AccessibleName="Found PCSX2 installations", DropDownStyle=ComboBoxStyle.DropDownList, Dock=DockStyle.Fill };
                var gameChoices=new ComboBox { AccessibleName="Found BT2 dumps", DropDownStyle=ComboBoxStyle.DropDownList, Dock=DockStyle.Fill };
                layout.Controls.Add(new Label { Text="Found PCSX2", AutoSize=true },0,4); layout.Controls.Add(emulatorChoices,1,4); layout.SetColumnSpan(emulatorChoices,2);
                layout.Controls.Add(new Label { Text="Found games", AutoSize=true },0,5); layout.Controls.Add(gameChoices,1,5); layout.SetColumnSpan(gameChoices,2);
                var scanStatus=new TextBox { AccessibleName="Automatic search status", ReadOnly=true, Multiline=true, Height=65, Dock=DockStyle.Fill, Text="Find automatically searches your PCSX2 library and local drives. You can cancel the settings window while it searches." };
                layout.Controls.Add(scanStatus,0,6); layout.SetColumnSpan(scanStatus,3);
                var emulatorRows=new List<Dictionary<string,object>>(); var gameRows=new List<Dictionary<string,object>>();
                emulatorChoices.SelectedIndexChanged+=delegate {
                    if(emulatorChoices.SelectedIndex>=0) { var row=emulatorRows[emulatorChoices.SelectedIndex]; emulatorBox.Text=(string)row["path"]; mode.Checked=(bool)row["portable"]; }
                };
                gameChoices.SelectedIndexChanged+=delegate { if(gameChoices.SelectedIndex>=0) gameBox.Text=(string)gameRows[gameChoices.SelectedIndex]["path"]; };
                var buttons=new FlowLayoutPanel { Dock=DockStyle.Fill, AutoSize=true };
                var detect=new Button { Text="&Find automatically", AccessibleName="Find PCSX2 and BT2 automatically", AutoSize=true };
                detect.Click+=async delegate {
                    detect.Enabled=false; scanStatus.Text="Searching for PCSX2 and BT2. This can take up to 30 seconds.";
                    string previousEmulator=emulatorBox.Text, previousGame=gameBox.Text;
                    try {
                        var data=await Task.Run(()=>Request(new Dictionary<string,object>{{"action","discover"},{"emulator",previousEmulator},{"game",previousGame}}));
                        if(dialog.IsDisposed) return;
                        emulatorChoices.Items.Clear(); gameChoices.Items.Clear(); emulatorRows.Clear(); gameRows.Clear();
                        foreach(Dictionary<string,object> row in (ArrayList)data["emulators"]) { emulatorRows.Add(row); emulatorChoices.Items.Add((string)row["label"]); }
                        foreach(Dictionary<string,object> row in (ArrayList)data["games"]) { gameRows.Add(row); gameChoices.Items.Add((string)row["label"]); }
                        if(emulatorRows.Count==1 && emulatorBox.Text==previousEmulator) emulatorChoices.SelectedIndex=0;
                        int verified=gameRows.FindAll(row=>(bool)row["verified"]).Count;
                        if((gameRows.Count==1 || verified==1) && gameBox.Text==previousGame) gameChoices.SelectedIndex=0;
                        scanStatus.Text=(string)data["message"]+" Choose a result if more than one was found, then Save.";
                        scanStatus.Focus(); scanStatus.SelectAll();
                    } catch(Exception error) { if(!dialog.IsDisposed) scanStatus.Text="Search could not finish: "+error.Message; }
                    finally { if(!dialog.IsDisposed) detect.Enabled=true; }
                };
                var accept=new Button { Text="&Save", AccessibleName="Save settings", AutoSize=true, TabIndex=4 };
                var cancel=new Button { Text="Cancel", DialogResult=DialogResult.Cancel, AutoSize=true, TabIndex=5 };
                accept.Click+=delegate {
                    string chosenEmulator=emulatorBox.Text.Trim(), chosenGame=gameBox.Text.Trim();
                    if((chosenEmulator.Length>0 && !File.Exists(chosenEmulator)) || (chosenGame.Length>0 && !File.Exists(chosenGame))) {
                        MessageBox.Show(dialog,"Choose existing files, or leave the paths blank to open the game yourself.","Check paths"); return;
                    }
                    try {
                        var settings=new Dictionary<string,object>{{"python",python},{"emulator",chosenEmulator},{"game",chosenGame},{"portable",mode.Checked}};
                        File.WriteAllText(settingsPath,json.Serialize(settings),Encoding.UTF8);
                        emulator=chosenEmulator; game=chosenGame; portable=mode.Checked; dialog.DialogResult=DialogResult.OK;
                    } catch(Exception error) { ShowError("Could not save settings",error); }
                };
                buttons.Controls.AddRange(new Control[]{detect,accept,cancel});
                layout.Controls.Add(buttons,1,7); layout.SetColumnSpan(buttons,2);
                for(int i=0;i<8;i++) layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                foreach(Control control in layout.Controls) control.Margin=new Padding(4,8,4,8);
                dialog.Controls.Add(layout); dialog.AcceptButton=accept; dialog.CancelButton=cancel;
                dialog.Shown+=delegate { if(!File.Exists(emulatorBox.Text) || !File.Exists(gameBox.Text)) detect.PerformClick(); else emulatorBox.Focus(); };
                dialog.ShowDialog(this);
            }
        }
        string AsciiJson(Dictionary<string,object> request)
        {
            var encoded=new StringBuilder();
            foreach(char c in json.Serialize(request))
                if(c>127) encoded.Append("\\u"+((int)c).ToString("x4")); else encoded.Append(c);
            return encoded.ToString();
        }
        void Enqueue(string text)
        {
            string dropped;
            while(messages.Count>=256) messages.TryDequeue(out dropped);
            messages.Enqueue(text);
        }
        ProcessStartInfo WorkerInfo(string arguments)
        {
            string bundled=Path.Combine(root,"worker","guide-worker.exe");
            bool packaged=File.Exists(bundled);
            if (!packaged && !File.Exists(python)) throw new FileNotFoundException("The guide runtime could not be found. Extract the complete release ZIP.");
            var info = new ProcessStartInfo(packaged ? bundled : python,packaged ? arguments : "-u "+Quote(Path.Combine(root,"tools","guide_host.py"))+" "+arguments) {
                WorkingDirectory=root, UseShellExecute=false, CreateNoWindow=true,
                RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true,
                StandardOutputEncoding=Encoding.UTF8, StandardErrorEncoding=Encoding.UTF8
            };
            info.EnvironmentVariables["BT2_DATA_DIR"]=dataRoot;
            info.EnvironmentVariables["BT2_EMULATOR"]=emulator;
            info.EnvironmentVariables["BT2_PORTABLE"]=portable ? "1" : "0";
            info.EnvironmentVariables["PYTHONUNBUFFERED"]="1";
            return info;
        }
        Dictionary<string,object> Request(Dictionary<string,object> request)
        {
            using (var process=new Process { StartInfo=WorkerInfo("--request") }) {
                process.StartInfo.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
                process.Start();
                var output=process.StandardOutput.ReadToEndAsync();
                var errors=process.StandardError.ReadToEndAsync();
                process.StandardInput.Write(AsciiJson(request)); process.StandardInput.Close();
                if (!process.WaitForExit((string)request["action"]=="discover" ? 35000 : 10000)) { process.Kill(); throw new Exception("The guide setup request timed out."); }
                if (process.ExitCode!=0) throw new Exception(errors.Result);
                var response=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(output.Result);
                if (!(bool)response["ok"]) throw new Exception((string)response["error"]);
                return (Dictionary<string,object>)response["data"];
            }
        }
        void RefreshMaps()
        {
            try {
                var old=maps.SelectedItem as MapItem;
                var data=Request(new Dictionary<string,object>{{"action","status"}});
                save.Text=(string)data["save"];
                maps.Items.Clear();
                foreach (Dictionary<string,object> row in (ArrayList)data["maps"]) {
                    var item=new MapItem { Key=(string)row["fingerprint"], Label=(string)row["label"], Name=(string)row["name"] };
                    maps.Items.Add(item);
                    if (old!=null && old.Key==item.Key) maps.SelectedItem=item;
                }
                if (maps.SelectedIndex<0 && maps.Items.Count>0) maps.SelectedIndex=0;
                rename.Enabled=maps.SelectedItem!=null && worker==null;
            } catch (Exception error) { ShowError("Could not read the saved maps",error); }
        }
        void RenameMap()
        {
            var item=maps.SelectedItem as MapItem;
            if (item==null || worker!=null) return;
            try {
                var data=Request(new Dictionary<string,object>{{"action","rename"},{"fingerprint",item.Key},{"name",mapName.Text}});
                latest.Text=(string)data["message"];
                RefreshMaps(); latest.Focus(); latest.SelectAll();
            } catch (Exception error) { ShowError("Could not save the map name",error); }
        }
        void StartGuide()
        {
            if (worker!=null) return;
            try {
                Directory.CreateDirectory(Path.Combine(dataRoot,"logs"));
                log=new StreamWriter(Path.Combine(dataRoot,"logs","desktop-"+DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")+".log"),false,Encoding.UTF8);
                log.AutoFlush=true;
                worker=new Process { StartInfo=WorkerInfo(speech.Checked ? "" : "--silent") };
                worker.StartInfo.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
                worker.OutputDataReceived+=delegate(object sender,DataReceivedEventArgs e) { if(e.Data!=null) Enqueue(e.Data); };
                worker.ErrorDataReceived+=delegate(object sender,DataReceivedEventArgs e) { if(e.Data!=null) Enqueue("Error: "+e.Data); };
                worker.Start(); worker.BeginOutputReadLine(); worker.BeginErrorReadLine();
                start.Enabled=false; stop.Enabled=true; speech.Enabled=false;
                rename.Enabled=false; mapName.Enabled=false; stopping=false;
                status.Text="Running"; stop.Focus();
            } catch (Exception error) {
                if(worker!=null) { worker.Dispose(); worker=null; }
                if(log!=null) { log.Dispose(); log=null; }
                ShowError("Could not start the guide",error);
            }
        }
        void StopGuide()
        {
            if(worker==null || stopping) return;
            stopping=true; stopStarted=DateTime.UtcNow; stop.Enabled=false; status.Text="Stopping";
            try { worker.StandardInput.WriteLine("stop"); worker.StandardInput.Flush(); worker.StandardInput.Close(); }
            catch (InvalidOperationException) { }
            catch (IOException) { }
        }
        void DrainMessages()
        {
            string line; int count=0;
            while(count++<100 && messages.TryDequeue(out line)) {
                latest.Text=line;
                history.AppendText(line+Environment.NewLine);
                if(history.TextLength>50000) history.Text=history.Text.Substring(history.TextLength-35000);
                if(log!=null) {
                    try { log.WriteLine(line); }
                    catch(IOException) { log=null; Enqueue("File logging is unavailable; messages remain in this window."); }
                }
            }
            if(worker==null) return;
            if(stopping && !worker.HasExited && (DateTime.UtcNow-stopStarted).TotalSeconds>15) {
                // Only our own worker can be stopped. Never terminate PCSX2.
                worker.Kill(); Enqueue("The guide worker did not finish stopping and was closed.");
            }
            if(worker.HasExited) {
                int code=worker.ExitCode; worker.WaitForExit(); worker.Dispose(); worker=null;
                if(log!=null) { log.Dispose(); log=null; }
                status.Text=code==0 ? "Stopped" : "Stopped after an error. Read the message history.";
                start.Enabled=true; stop.Enabled=false; speech.Enabled=true; mapName.Enabled=true;
                rename.Enabled=maps.SelectedItem!=null;
                stopping=false;
                if(closing) { timer.Stop(); Close(); }
                else { RefreshMaps(); start.Focus(); }
            }
        }
        async void OpenGame()
        {
            if(!File.Exists(emulator) || !File.Exists(game)) {
                Configure();
                if(!File.Exists(emulator) || !File.Exists(game)) return;
            }
            open.Enabled=false;
            try {
                var data=await Task.Run(()=>Request(new Dictionary<string,object>{{"action","prepare"},{"emulator",emulator},{"portable",portable}}));
                if(IsDisposed) return;
                latest.Text=(string)data["message"];
                if((bool)data["running"]) {
                    MessageBox.Show(this,latest.Text+"\n\nPCSX2 is already open. Use Alt+Tab to switch to it.","PCSX2 connection");
                    return;
                }
                Process.Start(new ProcessStartInfo(emulator,(portable ? "-portable " : "")+"-- "+Quote(game)) {
                    UseShellExecute=false, WorkingDirectory=Path.GetDirectoryName(emulator)
                });
                latest.Text+=" Game opened normally from your configured memory card.";
            } catch (Exception error) { if(!IsDisposed) ShowError("Could not open the game",error); }
            finally { if(!IsDisposed) open.Enabled=true; }
        }
        void OnClosing(object sender,FormClosingEventArgs e)
        {
            if(worker!=null) { e.Cancel=true; closing=true; StopGuide(); }
        }
        void ShowError(string message,Exception error)
        {
            latest.Text=message+": "+error.Message;
            MessageBox.Show(this,latest.Text,"DBZ BT2 Guide",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }

    static class Program
    {
        [STAThread]
        static void Main()
        {
            bool created;
            using(var mutex=new Mutex(true,"Local\\DBZBT2AccessibilityDesktop",out created)) {
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                if(!created) { MessageBox.Show("The guide window is already open. Use Alt+Tab to find it.","DBZ BT2 Guide"); return; }
                try { Application.Run(new GuideForm(AppDomain.CurrentDomain.BaseDirectory)); }
                catch(Exception error) { MessageBox.Show(error.Message,"Could not open DBZ BT2 Guide",MessageBoxButtons.OK,MessageBoxIcon.Error); }
            }
        }
    }
}
