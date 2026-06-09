import asyncio
import re
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.account import UpdateStatusRequest
import database as db

class AccountManager:
    def __init__(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.clients = {}
        self.online_tasks = {}

    async def _join_channel(self, client, link: str):
        try:
            match = re.search(r't\.me/\+(.+)', link)
            if match:
                invite_hash = match.group(1).split('_')[0]
                await client(ImportChatInviteRequest(invite_hash))
                return True, "✅ join request sent"
            else:
                username = link.strip("/").replace("https://t.me/", "").replace("http://t.me/", "")
                if not username:
                    return False, "invalid link"
                entity = await client.get_entity(username)
                await client(JoinChannelRequest(entity))
                return True, f"✅ joined @{username}"
        except errors.FloodWaitError as e:
            return False, f"⏳ flood wait {e.seconds}s"
        except Exception as e:
            err = str(e).lower()
            if "successfully requested" in err:
                return True, "✅ join request sent"
            return False, f"❌ {str(e)}"

    async def _keep_online_for_1hour(self, client, phone):
        try:
            await client(UpdateStatusRequest(offline=False))
            print(f"🟢 {phone} forced online")
        except:
            pass
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 3600:
            await asyncio.sleep(60)
            try:
                await client(UpdateStatusRequest(offline=False))
            except:
                pass
        try:
            await client(UpdateStatusRequest(offline=True))
            print(f"⏰ {phone} offline after 1 hour")
        except:
            pass
        if phone in self.online_tasks:
            del self.online_tasks[phone]

    async def start_all_accounts(self):
        accounts = await db.get_all_accounts()
        for _, phone, session_str in accounts:
            await self._add_client(phone, session_str)

    async def _add_client(self, phone: str, session_str: str):
        client = TelegramClient(
            StringSession(session_str),
            self.api_id,
            self.api_hash,
            connection_retries=5,
            retry_delay=3,
            timeout=60,
            request_retries=3
        )
        try:
            await client.connect()
            if await client.is_user_authorized():
                self.clients[phone] = client
                print(f"✅ {phone} connected (idle)")
            else:
                print(f"⚠️ {phone} not authorized – re-login needed")
        except Exception as e:
            print(f"❌ {phone} connection error: {e}")
            await asyncio.sleep(5)
            try:
                await client.connect()
                self.clients[phone] = client
                print(f"✅ {phone} reconnected (idle)")
            except Exception as e2:
                print(f"❌ {phone} failed to reconnect: {e2}")

    async def add_new_account(self, phone: str, session_str: str):
        await db.add_account(phone, session_str)
        await self._add_client(phone, session_str)

    async def join_and_go_online(self, invite_link: str, delay: int, count: int, progress_callback=None):
        all_phones = list(self.clients.keys())
        if count > len(all_phones):
            return [f"❌ Only {len(all_phones)} accounts available."], []
        selected = all_phones[:count]

        # Start online immediately for all selected accounts
        for phone in selected:
            if phone in self.online_tasks:
                self.online_tasks[phone].cancel()
            task = asyncio.create_task(self._keep_online_for_1hour(self.clients[phone], phone))
            self.online_tasks[phone] = task

        results = []
        success = []
        total = len(selected)
        for idx, phone in enumerate(selected):
            client = self.clients[phone]
            ok, msg = await self._join_channel(client, invite_link)
            if ok:
                success.append(phone)
                await db.log_activity("JOIN", invite_link, phone)
                results.append(f"✅ {phone}: {msg}")
            else:
                results.append(f"❌ {phone}: {msg}")
            if progress_callback:
                await progress_callback(idx+1, total, len(success), idx+1 - len(success))
            if idx < total - 1 and delay > 0:
                await asyncio.sleep(delay)

        for phone in selected:
            results.append(f"🟢 {phone} is ONLINE for 1 hour (forced)")
        summary = f"\n📊 Delay: {delay}s | Requested: {count} | Joined: {len(success)}"
        results.append(summary)
        return results, success

    async def leave_specific(self, entity_input: str):
        results = []
        for phone, client in self.clients.items():
            try:
                entity = await client.get_entity(entity_input)
                await client(LeaveChannelRequest(entity))
                results.append(f"✅ {phone} left {entity_input}")
                await db.log_activity("LEAVE", entity_input, phone)
            except Exception as e:
                results.append(f"❌ {phone} error: {str(e)}")
        return results

    async def leave_all_channels(self):
        all_results = []
        for phone, client in self.clients.items():
            results = []
            try:
                dialogs = await client.get_dialogs()
                for dialog in dialogs:
                    if dialog.is_channel or dialog.is_group:
                        try:
                            await client(LeaveChannelRequest(dialog.entity))
                            results.append(f"✅ left {dialog.name}")
                            await db.log_activity("LEAVE_ALL", dialog.name, phone)
                        except:
                            pass
                if results:
                    all_results.append(f"📱 {phone}:\n" + "\n".join(results))
                else:
                    all_results.append(f"📱 {phone}: no channels/groups to leave.")
            except Exception as e:
                all_results.append(f"❌ {phone} error: {str(e)}")
        return all_results

    async def react_to_post(self, channel_link: str, message_id: int, emoji: str = "👍"):
        results = []
        for phone, client in self.clients.items():
            try:
                entity = await client.get_entity(channel_link)
                await client.send_reaction(entity, message_id, emoji)
                results.append(f"✅ {phone} reacted with {emoji}")
                await db.log_activity("REACT", f"{channel_link} msg {message_id}", phone)
            except Exception as e:
                results.append(f"❌ {phone} error: {str(e)}")
        return results

    async def join_live_stream(self, stream_link: str):
        results = []
        for phone, client in self.clients.items():
            try:
                entity = await client.get_entity(stream_link)
                await client(JoinChannelRequest(entity))
                results.append(f"✅ {phone} joined live stream")
                await db.log_activity("JOIN_LIVE", stream_link, phone)
            except Exception as e:
                results.append(f"❌ {phone} error: {str(e)}")
        return results

    async def get_active_sessions(self):
        return len(self.clients)

    async def get_accounts_list(self):
        return list(self.clients.keys())

    async def stop_all(self):
        for t in self.online_tasks.values():
            t.cancel()
        for c in self.clients.values():
            await c.disconnect()
