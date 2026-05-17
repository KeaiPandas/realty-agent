// Contact picker
import { state, escHtml, getDisplayName, getSecondaryName } from './state.js';
import { fetchContacts } from './api.js';

export async function loadContacts() {
  const cpInput = document.getElementById('cpInput');
  cpInput.value = '加载中...';
  try {
    const data = await fetchContacts();
    if (!data) { cpInput.value = '加载失败'; return; }
    state.contactsList = data;
    cpInput.value = '';
    cpInput.placeholder = '搜索联系人...';
    cpInput.readOnly = false;
  } catch (e) {
    cpInput.value = '网络错误';
  }
}

export function toggleContactPicker() {
  state.cpOpen ? closeContactPicker() : openContactPicker();
}

export function openContactPicker() {
  state.cpOpen = true;
  document.getElementById('cpDropdown').classList.add('open');
  const searchInput = document.getElementById('cpSearch');
  searchInput.value = '';
  renderContactList(state.contactsList);
  setTimeout(() => searchInput.focus(), 50);
}

export function closeContactPicker() {
  state.cpOpen = false;
  document.getElementById('cpDropdown').classList.remove('open');
}

export function renderContactList(contacts) {
  const list = document.getElementById('cpList');
  list.innerHTML = '';
  const allItem = document.createElement('div');
  allItem.className = 'contact-picker-item special' + (state.selectedContactId === '__all__' ? ' selected' : '');
  allItem.innerHTML = '<span class="cp-name">所有人</span><span class="cp-sub">' + contacts.length + ' 个联系人</span>';
  allItem.onclick = () => selectContact('__all__', '所有人');
  list.appendChild(allItem);
  if (contacts.length === 0) {
    list.innerHTML += '<div class="contact-picker-empty">无匹配联系人</div>';
    return;
  }
  contacts.forEach(c => {
    const item = document.createElement('div');
    item.className = 'contact-picker-item' + (state.selectedContactId === c.wxid ? ' selected' : '');
    const primary = getDisplayName(c);
    const secondary = getSecondaryName(c);
    item.innerHTML = '<span class="cp-name">' + escHtml(primary) + '</span>' +
      (secondary ? '<span class="cp-sub">' + escHtml(secondary) + '</span>' : '');
    item.onclick = () => selectContact(c.wxid, primary);
    list.appendChild(item);
  });
}

export function filterContacts() {
  const query = document.getElementById('cpSearch').value.trim().toLowerCase();
  if (!query) { renderContactList(state.contactsList); return; }
  renderContactList(state.contactsList.filter(c => {
    const d = getDisplayName(c).toLowerCase();
    const s = getSecondaryName(c).toLowerCase();
    const w = c.wxid.toLowerCase();
    return d.includes(query) || s.includes(query) || w.includes(query);
  }));
}

export function selectContact(wxid, name) {
  state.selectedContactId = wxid;
  state.selectedContactName = name;
  const cpInput = document.getElementById('cpInput');
  cpInput.value = wxid === '__all__' ? '所有人' : name;
  cpInput.classList.add('has-value');
  closeContactPicker();
}

// Close picker on outside click
document.addEventListener('click', (e) => {
  const picker = document.getElementById('contactPicker');
  if (state.cpOpen && !picker.contains(e.target)) closeContactPicker();
});
