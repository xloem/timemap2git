#!/usr/bin/python

import sys, getopt, requests, datetime

config = {
	'verbose' : False,
	'committer' : '<donotreply@localhost>',
	'branch' : 'master'
}
persist = {
	'mark' : 1,
	'session' : requests.Session(),
	'checkpoint' : True
}

def help():
	sys.stderr.write("Usage: %s [OPTION]... URL\n" % sys.argv[0])
	sys.stderr.write("Download web archive history for URL to be piped to `git fast-import'.\n")
	sys.stderr.write("\n")
	sys.stderr.write("  -h, --help                       display this help message\n")
	sys.stderr.write("  -v, --verbose                    list GET requests on stderr\n")
	sys.stderr.write("  -b, --branch=REF                 branch to make the commits on\n")
	sys.stderr.write("                                   defaults to master\n")
	sys.stderr.write("  -c, --committer='[NAME ]<EMAIL>' whom to list as committer\n")
	sys.stderr.write("                                   defaults to '%s'\n" % config['committer'])
	sys.stderr.write("  -a, --author='[NAME ]<EMAIL>'    whom to list as author\n")
	sys.stderr.write("                                   defaults to committer\n")
	sys.stderr.write("  -s, --since=DATE                 ignore information prior to DATE\n")
	sys.stderr.write("  -p, --parent=COMMIT              give the 1st commit this parent\n")
	#sys.stderr.write("                                   defaults to the current branch value\n")
	sys.stderr.write("                                   without -p the 1st commit will have no parent\n")


def main(argv):
	global config
	try:
		opts, args = getopt.getopt(argv,"hvb:c:a:s:p:",["help","verbose","branch=","committer=","author=","since=","parent="])
	except getopt.GetoptError:
		help()
		sys.exit(2)
	for opt, arg in opts:
		if opt in ("-h", "--help"):
			help()
			sys.exit()
		elif opt in ("-v", "--verbose"):
			config['verbose'] = True
		elif opt in ("-b", "--branch"):
			config['branch'] = arg
		elif opt in ("-c", "--committer"):
			config['committer'] = arg
		elif opt in ("-a", "--author"):
			config['author'] =  arg
		elif opt in ("-s", "--since"):
			since = None
			for fmt in (
				"%c %z",
				"%Y-%m-%d %H:%M:%S %z",
				"%a, %d %b %Y %H:%M:%S %z",
				"%Y-%m-%d"
				):
				try:
					since = datetime.datetime.strptime(arg, fmt)
					break
				except ValueError:
					continue
			if not since:
				sys.stderr.write("Failed to parse date.  Just copy-paste it from git log.\n")
				sys.exit(2)
			config['since'] = since
		elif opt in ("-p", "--parent"):
			config['parent'] = arg
	if len(args) != 1:
		help()
		sys.exit(2)
	url = args[0]
	processTimeMap("http://labs.mementoweb.org/timemap/json/" + url)

def parseDatetime(str):
	str = str.replace("Z","+0000")
	return datetime.datetime.strptime(str, "%Y-%m-%dT%H:%M:%S%z")

def localZ():
	minutes = round((datetime.datetime.now() - datetime.datetime.utcnow()).total_seconds() / 60)
	return "%0+.2i%0.2i" % (minutes / 60, minutes % 60)

def uriToPath(uri):
	if uri[-1] == "/":
		uri = uri + "index.html"
	return uri[uri.find("//")+2:]

def get(url):
	if config['verbose']:
		sys.stderr.write("GET %s\n" % url)
	while True:
		try:
			r = persist['session'].get(url, allow_redirects=False)
			persist['lastresponse'] = r
			r.raise_for_status()
			return r
		except requests.exceptions.RequestException as e:
			sys.stderr.write("%s\n" % e)
			if 'checkpoint' not in persist:
				persist['checkpoint'] = True
				print('checkpoint\n')
			pass
		

def processTimeMap(url):
	r = get(url)
	timemap = r.json()
	if 'mementos' in timemap:
		mementos=timemap['mementos']['list']
		for memento in mementos:
			dt = parseDatetime(memento['datetime'])
			if 'since' in config and config['since'] > dt:
				continue
			processMemento(dt, memento['uri'])
	if 'timemap_index' in timemap:
		for chunk in timemap['timemap_index']:
			if 'since' in config and 'until' in chunk and config['since'] > parseDatetime(chunk['until']):
				continue
			processTimeMap(chunk['uri'])


def processMemento(date, uri):
	global persist

	# tell archive.org not to mangle content
	uri = uri.replace("/http","id_/http")

	r = get(uri)
	print('commit ' + config['branch'])
	print('mark :' + str(persist['mark']))
	if 'author' in config:
		print('author ' + config['author'] + ' ' + date.dtrftime("%s %z"))
	else:
		print('author ' + config['committer'] + ' ' + date.strftime("%s %z"))
	print('committer ' + config['committer'] +' ' + datetime.datetime.now().strftime("%s " + localZ()))
	print('data 0')
	if persist['mark'] > 1:
		print('from :' + str(persist['mark'] - 1))
	elif 'parent' in config:
		print('from ' + config['parent'])
	persist['mark'] += 1

	processResponseData(r)

	if 'checkpoint' in persist:
		del persist['checkpoint']

def processResponseData(r):
	if r.is_redirect:
		redirect = r.headers['Location']
		if config['verbose']:
			sys.stderr.write("Location: %s\n" % redirect)
		if redirect.startswith("http"):
			url2 = redirect
		else:
			if "/http" in redirect:
				# this links to a differently-timestamped snapshot
				return
			if redirect[0] == "/":
				baselen = r.url.find("/",r.url.find("/http")+9)
			else:
				baselen = r.url.rfind("/") + 1
			url2 = r.url[0:baselen] + redirect

		print('M 120000 inline ' + uriToPath(r.links['original']['url']))
		r2 = get(url2)
		target = r2.links['original']['url']
		print('data ' + str(len(target)))
		print(target)

		processResponseData(r2)
	else:
		print('M 644 inline ' + uriToPath(r.links['original']['url']))
		print('data ' + str(len(r.content)))
		sys.stdout.flush()
		sys.stdout.buffer.write(r.content)

if __name__ == "__main__":
	try:
		main(sys.argv[1:])
	except KeyError as e:
		sys.stdout.write("%s\n%s\n" % (persist['lastresponse'], e))
		raise(e)
