import wx
import requests
import re
import webbrowser

def get_latest_release(repo):
	url = f"https://api.github.com/repos/{repo}/releases"
	response = requests.get(url)
	if response.status_code == 200:
		releases = response.json()
		release = releases[0]
		name = release['name']
		tag = release['tag_name']
		url = release['html_url']
		matches = re.findall(r'\d+', tag)
		numbers = [int(match) for match in matches]
		build = numbers[-1]
		return name, build, url

def displayUpdate(name, url):
	with wx.MessageDialog(None, f"{name} is available. Would you like to open the link to download?", 'New Update', wx.YES_NO|wx.ICON_QUESTION) as dlg:
		dlg.SetYesNoLabels("Yes", "No")
		if dlg.ShowModal() == wx.ID_YES:
			webbrowser.open(url)

def check_update(current):
	repo = "chigkim/vollama"
	name, build, url = get_latest_release(repo)
	if build>current: displayUpdate(name, url)
