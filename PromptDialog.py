import wx
import pandas as pd
import requests
import io
from Settings import SettingsManager
import os

class PromptDialog(wx.Dialog):
	def __init__(self, parent, prompt=""):
		super().__init__(parent, title="Edit Prompts", size=(400, 300))

		self.panel = wx.Panel(self)
		self.prompt_file = os.path.join(SettingsManager().config_dir, "prompts.csv")
		if os.path.exists(self.prompt_file):
			self.prompt_data = pd.read_csv(self.prompt_file)
			self.prompt_data = self.prompt_data.sort_values(by='act').reset_index(drop=True)
		else:
			self.prompt_data = pd.DataFrame(columns=["act", "prompt"])
		# UI Elements
		self.act_list = wx.ListBox(self.panel, choices=self.prompt_data['act'].tolist())
		self.prompt_text = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE)
		self.new_button = wx.Button(self.panel, label="New")
		self.save_button = wx.Button(self.panel, label="Save")
		self.delete_button = wx.Button(self.panel, label="Delete")
		self.update_button = wx.Button(self.panel, label="Download&Update")
		self.set_button = wx.Button(self.panel, label='Set Prompt', id=wx.ID_OK)
		self.cancel_button = wx.Button(self.panel, label='Cancel', id=wx.ID_CANCEL)

		self.sizer = wx.BoxSizer(wx.VERTICAL)
		self.sizer.Add(self.act_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
		self.sizer.Add(self.prompt_text, proportion=2, flag=wx.EXPAND | wx.ALL, border=5)
		self.button_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.button_sizer.Add(self.new_button, flag=wx.ALL, border=5)
		self.button_sizer.Add(self.save_button, flag=wx.ALL, border=5)
		self.button_sizer.Add(self.delete_button, flag=wx.ALL, border=5)
		self.button_sizer.Add(self.update_button, flag=wx.ALL, border=5)

		self.button_sizer.Add(self.set_button, flag=wx.ALL, border=5)
		self.button_sizer.Add(self.cancel_button, flag=wx.ALL, border=5)
		self.sizer.Add(self.button_sizer, flag=wx.ALIGN_CENTER)

		self.panel.SetSizerAndFit(self.sizer)

		# Bind Events
		self.act_list.Bind(wx.EVT_LISTBOX, self.on_act_selected)
		self.new_button.Bind(wx.EVT_BUTTON, self.on_new)
		self.save_button.Bind(wx.EVT_BUTTON, self.on_save)
		self.delete_button.Bind(wx.EVT_BUTTON, self.on_delete)
		self.update_button.Bind(wx.EVT_BUTTON, self.on_update)

		result = self.prompt_data[self.prompt_data['prompt'] == prompt]
		if not result.empty:
			selection_index = result.index[0]
			self.act_list.SetSelection(selection_index)
			self.prompt_text.SetValue(self.prompt_data.at[selection_index, 'prompt'])

	def on_act_selected(self, event):
		selection = self.act_list.GetSelection()
		if selection != wx.NOT_FOUND:
			prompt = self.prompt_data.iloc[selection]['prompt']
			self.prompt_text.SetValue(prompt)

	def on_new(self, event):
		act = wx.GetTextFromUser("Enter new act:", "New Act")
		if act:
			self.prompt_data = self.prompt_data._append({'act': act, 'prompt': ''}, ignore_index=True)
			self.prompt_data = self.prompt_data.sort_values(by='act').reset_index(drop=True)
			self.act_list.Set(self.prompt_data['act'].tolist())
			self.act_list.SetSelection(self.prompt_data.index[self.prompt_data['act'] == act].tolist()[0])
			self.prompt_text.SetValue("")

	def on_save(self, event):
		selection = self.act_list.GetSelection()
		if selection != wx.NOT_FOUND:
			self.prompt_data.at[selection, 'prompt'] = self.prompt_text.GetValue()
			self.prompt_data.to_csv(self.prompt_file, index=False)

	def on_delete(self, event):
		selection = self.act_list.GetSelection()
		if selection != wx.NOT_FOUND:
			self.prompt_data = self.prompt_data.drop(selection).reset_index(drop=True)
			self.prompt_data = self.prompt_data.sort_values(by='act').reset_index(drop=True)
			self.prompt_data.to_csv(self.prompt_file, index=False)
			self.act_list.Set(self.prompt_data['act'].tolist())
			self.prompt_text.SetValue("")

	def on_update(self, event):
		try:
			url = 'https://github.com/f/awesome-chatgpt-prompts/raw/main/prompts.csv'
			response = requests.get(url)
			response.raise_for_status()
			new_prompt_data = pd.read_csv(io.StringIO(response.text))
			combined_data = pd.concat([self.prompt_data, new_prompt_data]).drop_duplicates(subset='act', keep='last').reset_index(drop=True)
			self.prompt_data = combined_data.sort_values(by='act').reset_index(drop=True)
			self.prompt_data.to_csv(self.prompt_file, index=False)

			self.act_list.Set(self.prompt_data['act'].tolist())
			self.prompt_text.SetValue("")
			wx.MessageBox("Prompts updated successfully.", "Info", wx.OK | wx.ICON_INFORMATION)
		except requests.RequestException as e:
			wx.MessageBox(f"Failed to update prompts: {e}", "Error", wx.OK | wx.ICON_ERROR)
