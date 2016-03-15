#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
FrozenIdea2 event driven IRC bot class
by  Bystroushaak (bystrousak@kitakitsune.org)
and Thyrst (https://github.com/Thyrst)
"""
# Interpreter version: python 2.7
#
# TODO
#   :irc.cyberyard.net 401 TODObot � :No such nick/channel
#   ERROR :Closing Link: TODObot[31.31.73.113] (Excess Flood)
#
# Imports =====================================================================
import time
import socket
import select
from collections import namedtuple


# Variables ===================================================================
ENDL = "\r\n"


# Functions & classes =========================================================
class QuitException(Exception):
    def __init__(self, message):
        super(self, message)


class ParsedMsg(namedtuple("ParsedMsg", "nick type text")):
    pass


class FrozenIdea2(object):
    """
    FrozenIdea2 IRC bot template class.

    This class allows you to write easily event driven IRC bots.

    Notable properties:
        .real_name -- real name irc property - shown in whois
        .part_msg  -- message shown when IRC bot is leaving the channel
        .quit_msg  -- same as .part_msg, but when quitting
        .password  -- password for irc server (not channel)
        .chans     -- dict {"chan_name": [users,]}
        .verbose   -- should the bot print all incomming messages to stdin?
                      default False

    Raise QuitException if you wish to quit.
    """
    def __init__(self, nickname, server, port, join_list=None, lazy=False):
        self.nickname = nickname
        self.server = server
        self.port = port

        self.real_name = "FrozenIdea2 IRC bot"
        self.part_msg = "Fuck it, I quit."
        self.quit_msg = self.part_msg
        self.password = ""
        self.verbose = False

        self.socket_timeout = 60
        self.last_ping = 0
        self.default_ping_diff = 60 * 5  # 20m

        self.chans = {}
        self.join_list = join_list or []

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if not lazy:
            self.connect()

    def connect(self):
        """Connect socket to server"""
        self._socket.connect((self.server, int(self.port)))
        self._socket.setblocking(0)

    def _socket_send_line(self, line):
        """Send line thru socket. Adds ENDL if there is not already one."""
        if not line.endswith(ENDL):
            line += ENDL

        # lot of fun with this shit -- if you wan't to enjoy some unicode
        # errors, try sending "��"
        try:
            line = bytes(line)
        except UnicodeEncodeError:
            try:
                line = bytes(line.decode("utf-8"))
            except UnicodeEncodeError:
                line = bytearray(line, "ascii", "ignore")

        self._socket.send(line)

    def join(self, chan):
        """Join channel. Adds # before `chan`, if there is not already one."""
        if not chan.startswith("#"):
            chan = "#" + chan

        self._socket_send_line("JOIN " + chan)

    def join_all(self, chans=None):
        if chans is None:
            chans = self.join_list

        for chan in chans:
            if isinstance(chan, basestring):
                self.join(chan)
            elif type(chan) in [tuple, list]:
                for c in chan:
                    self.join(c)

    def rename(self, new_name):
        """Change .nickname to `new_name`."""
        if self.nickname != new_name:
            self.nickname = new_name
            self._socket_send_line("NICK " + new_name)

    def nickname_used(self, nickname):
        """Callback when `new_name` is already in use."""
        self.nickname = nickname

    def send_msg(self, to, msg, msg_type=0):
        """
        Send message to given user or channel.

        Args:
            to (str): User or channel.
            msg (str): Message.
            msg_type (int, default 0): Type of the message. `0` for normal
                     message, `1` for action message or `2` for notice.
        """
        line = [
            "PRIVMSG %s :%s" % (to, msg),
            "PRIVMSG %s :\x01ACTION %s\x01" % (to, msg),
            "NOTICE %s :%s" % (to, msg),
        ]

        try:
            line = line[int(msg_type)]
        except IndexError:
            line = "PRIVMSG " + to + " :" + msg

        self._socket_send_line(line)

    def send_array(self, to, array):
        """Send list of messages from `array` to `to`."""
        for line in array:
            self.send_msg(to, line)

    def part(self, chan, msg=None):
        """Leave channel `chan`. Show .part_msg if set."""
        if msg is None:
            msg = self.part_msg

        if self.verbose:
            print "---", chan

        self._socket_send_line("PART " + chan + " :" + str(msg))

    def quit(self):
        """Leave all channels and close connection. Show .quit_msg if set."""
        self._socket_send_line("QUIT :" + self.quit_msg)
        self._socket.close()

    def run(self):
        """
        Run the ._really_run() method and check it for errors to ensure clean
        quit.
        """
        try:
            self._really_run()

        except KeyboardInterrupt:
            self.on_quit()
            self.quit()
            return

        finally:
            self.on_quit()
            self.quit()
            raise

    def _really_run(self):
        """
        Lowlevel socekt operations.

        Read data from socket, join them into messages, react to pings and so
        on.
        """
        # check server password
        if self.password != "":
            self._socket_send_line("PASS " + self.password)

        # identify to server
        self._socket_send_line(
            "USER " + self.nickname + " 0 0 :" + self.real_name
        )
        self._socket_send_line("NICK " + self.nickname)

        msg_queue = ""
        while True:
            # select read doesn't consume that much resources from server
            ready_to_read, ready_to_write, in_error = select.select(
                [self._socket],
                [],
                [],
                self.socket_timeout
            )

            # timeouted, call .on_select_timeout()
            if not ready_to_read:
                self.on_select_timeout()
                continue

            # read 4096B from the server
            msg_queue += self._socket.recv(4096)

            # whole message doesn't arrived yet
            if ENDL not in msg_queue:
                continue

            # get arrived messages
            splitted = msg_queue.split(ENDL)
            msgs = splitted[:-1]  # all fully parsed messages
            msg_queue = splitted[-1]  # last one may not be whole

            for msg in msgs:
                msg = bytes(msg)
                if self.verbose:
                    print msg.strip()

                if msg.startswith("PING"):  # react o ping
                    ping_val = msg.split()[1].strip()
                    self._socket_send_line("PONG " + ping_val)
                    self.on_ping(ping_val)
                    self.last_ping = time.time()
                    continue

                try:
                    self._logic(msg)
                except QuitException:
                    self.on_quit()
                    self.quit()
                    return

    def _parse_msg(self, msg):
        """
        Get from who is the `msg`, which type it is and it's body.

        Returns tuple (from, type, msg_body).
        """
        msg = msg[1:]  # remove : from the beggining

        nickname, msg = msg.split(" ", 1)
        if ":" in msg:
            msg_type, msg = msg.split(":", 1)
        else:
            msg_type = msg.strip()
            msg = ""

        return ParsedMsg(
            nick=nickname.strip(),
            type=msg_type.strip(),
            text=msg.strip(),
        )

    def _logic(self, msg):
        """
        React to messages of given type. This is what calls event callbacks.
        """
        parsed = self._parse_msg(msg)

        # end of motd
        if parsed.type.startswith("376"):
            self.on_server_connected()

        # end of motd
        elif parsed.type.startswith("422"):
            self.on_server_connected()

        # nickname already in use
        elif parsed.type.startswith("433"):
            nickname = parsed.type.split(" ", 2)[1]
            self.nickname_used(nickname)

        # nick list
        elif parsed.type.startswith("353"):
            chan_name = "#" + parsed.type.split("#")[-1].strip()

            new_chan = True
            if chan_name in self.chans:
                del self.chans[chan_name]
                new_chan = False

            # get list of nicks, remove chan statuses (op/halfop/..)
            msg = map(
                lambda nick: nick if nick[0] not in "&@%+" else nick[1:],
                parsed.text.split()
            )

            self.chans[chan_name] = msg

            if new_chan:
                self.on_joined_to_chan(chan_name)

        # PM or chan message
        elif parsed.type.startswith("PRIVMSG"):
            nick, hostname = parsed.nick.split("!", 1)

            if nick == self.nickname:
                return

            # channel message
            if "#" in parsed.type:
                msg_type = parsed.type.split()[-1]

                if parsed.text.startswith("\x01ACTION"):
                    msg = parsed.text.split("\x01ACTION", 1)[1]
                    msg = msg.strip().strip("\x01")
                    self.on_channel_action_message(
                        msg_type,
                        nick,
                        hostname,
                        msg
                    )
                    return

                self.on_channel_message(
                    msg_type,
                    nick,
                    hostname,
                    parsed.text
                )
                return

            # pm msg
            if not parsed.text.startswith("\x01ACTION"):
                self.on_private_message(nick, hostname, parsed.text)
                return

            # pm action message
            msg = parsed.text.split("\x01ACTION", 1)[1].strip().strip("\x01")
            self.on_private_action_message(nick, hostname, msg)

        # kicked from chan
        elif parsed.type.startswith("404") or parsed.type.startswith("KICK"):
            msg_type = parsed.type.split()
            chan_name = msg_type[1]
            who = msg_type[2]
            msg = parsed.text.split(":")[0]  # TODO: parse kick message

            if who == self.nickname:
                self.on_kick(chan_name, msg)
                del self.chans[chan_name]
            else:
                if msg in self.chans[chan_name]:
                    self.chans[chan_name].remove(msg)
                self.on_somebody_kicked(chan_name, who, msg)

        # somebody joined channel
        elif parsed.type.startswith("JOIN"):
            nick = parsed.nick.split("!")[0].strip()
            try:
                chan_name = parsed.type.split()[1].strip()
            except IndexError:
                chan_name = parsed.text

            if nick != self.nickname:
                if nick not in self.chans[chan_name]:
                    self.chans[chan_name].append(nick)
                    self.on_somebody_joined_chan(chan_name, nick)

        # user renamed
        elif parsed.type == "NICK":
            old_nick = parsed.nick.split("!")[0].strip()

            for chan in self.chans.keys():
                if old_nick in self.chans[chan]:
                    self.chans[chan].remove(old_nick)
                    self.chans[chan].append(parsed.text)

            self.on_user_renamed(old_nick, parsed.text)

        # user leaved the channel
        elif parsed.type.startswith("PART"):
            chan = parsed.type.split()[-1]
            nick = parsed.nick.split("!")[0].strip()

            if nick in self.chans[chan]:
                self.chans[chan].remove(nick)

            self.on_somebody_leaved(chan, nick)

        # user quit the server
        elif parsed.type.startswith("QUIT"):
            nick = parsed.nick.split("!")[0].strip()

            for chan in self.chans.keys():
                if nick in self.chans[chan]:
                    self.chans[chan].remove(nick)

            self.on_somebody_quit(nick)

    def on_server_connected(self):
        """
        Called when bot is successfully connected to the server.

        By default, the +B mode is set to the bot and then bot joins all
        channels defined in :attr:`self.join_list`.
        """
        self._socket_send_line("MODE " + self.nickname + " +B")
        self.join_all()

    def on_joined_to_chan(self, chan_name):
        """Called when the bot has successfully joined the channel."""
        pass

    def on_somebody_joined_chan(self, chan_name, nick):
        """Called when somebody joined the channel you are in."""
        pass

    def on_channel_message(self, chan_name, nickname, hostname, msg):
        """
        Called when somebody posted message to a channel you are in.

        chan_name -- name of the channel (starts with #)
        nickname -- name of the origin of the message
        hostname -- users hostname - IP address usually
        msg -- users message
        """
        pass

    def on_private_message(self, nickname, hostname, msg):
        """
        Called when somebody send you private message.

        nickname -- name of the origin of the message
        hostname -- users hostname - IP address usually
        msg -- users message
        """
        pass

    def on_channel_action_message(self, chan_name, nickname, hostname, msg):
        """Called for channel message with action."""
        pass

    def on_private_action_message(self, nickname, hostname, msg):
        """Called for private message with action."""
        pass

    def on_user_renamed(self, old_nick, new_nick):
        """
        Called when user renamed himself.

        See .chans property, where user nicknames are tracked and stored.
        """
        pass

    def on_kick(self, chan_name, who):
        """
        Called when somebody kicks you from the channel.

        who -- who kicked you
        """
        pass

    def on_somebody_kicked(self, chan_name, who, kicked_user):
        """
        Called when somebody kick someone from `chan_name`.

        who -- who kicked `kicked_user`
        kicked_user -- person who was kicked from chan
        """
        pass

    def on_somebody_leaved(self, chan_name, nick):
        """Called when somebody leaves the channel."""
        pass

    def on_somebody_quit(self, nick):
        """Called when somebody leaves the server."""
        pass

    def on_select_timeout(self):
        """
        Called every 60s if nothing else is happening on the socket.

        This can be usefull source of event ticks.

        PS: Ping from server IS considered as something.
        """
        pass

    def on_ping(self, ping_val):
        """
        Called when the server sends PING to the bot. PONG is automatically
        sent back.

        By default, keep track of the :attr:`self.last_ping` and reconnect, if
        the diff is bigger than :attr:`self.default_ping_diff`.

        Attr:
            ping_val (str): Value of the ping message sent from the server.
        """
        now = time.time()

        if now - self.last_ping >= self.default_ping_diff:
            self.quit()
            self.connect()

    def on_quit(self):
        """
        Called when the bot is quitiing the server. Here should be your code
        which takes care of everything you need to do.
        """
        pass
