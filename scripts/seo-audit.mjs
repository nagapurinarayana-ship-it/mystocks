import { readFile } from 'node:fs/promises'

const SITE = 'https://mystocks-49k.pages.dev'
const sitemap = await readFile('sitemap.xml', 'utf8')
const urls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(match => match[1])
let failed = false
const titles = new Map()

function fail(message) {
  failed = true
  console.error(`FAIL ${message}`)
}

function count(source, regex) {
  return [...source.matchAll(regex)].length
}

if (!urls.length) fail('sitemap.xml has no URLs')
if (new Set(urls).size !== urls.length) fail('sitemap.xml contains duplicate URLs')
if (urls.some(url => /[?&]/.test(url))) fail('sitemap.xml contains parameter URLs')

for (const url of urls) {
  if (!url.startsWith(`${SITE}/`)) {
    fail(`sitemap URL is outside production origin: ${url}`)
    continue
  }

  const pathname = new URL(url).pathname
  const localPath = pathname === '/' ? 'index.html' : pathname.replace(/^\//, '')
  let html
  try {
    html = await readFile(localPath, 'utf8')
  } catch (_) {
    fail(`missing sitemap page ${localPath}`)
    continue
  }

  const title = html.match(/<title>([^<]+)<\/title>/i)?.[1]?.trim() || ''
  const description = html.match(/<meta\s+name=["']description["']\s+content=["']([^"']+)/i)?.[1]?.trim() || ''
  const canonical = html.match(/<link\s+rel=["']canonical["']\s+href=["']([^"']+)/i)?.[1] || ''
  const robots = html.match(/<meta\s+name=["']robots["']\s+content=["']([^"']+)/i)?.[1] || ''

  if (title.length < 20 || title.length > 75) fail(`${localPath}: title length should be 20-75 characters`)
  if (description.length < 70 || description.length > 180) fail(`${localPath}: description length should be 70-180 characters`)
  if (canonical !== url) fail(`${localPath}: canonical mismatch; expected ${url}`)
  if (!/index/.test(robots) || !/follow/.test(robots)) fail(`${localPath}: page must be index,follow`)
  if (!/max-image-preview:large/.test(robots)) fail(`${localPath}: allow large image previews`)
  if (count(html, /<h1\b/gi) !== 1) fail(`${localPath}: expected exactly one H1`)
  if (!html.includes('type="application/ld+json"')) fail(`${localPath}: structured data missing`)

  for (const marker of [
    'property="og:title"',
    'property="og:description"',
    'property="og:url"',
    'property="og:image"',
    'property="og:image:width"',
    'property="og:image:height"',
    'name="twitter:card"',
    'name="twitter:title"',
    'name="twitter:description"',
    'name="twitter:image"',
  ]) {
    if (!html.includes(marker)) fail(`${localPath}: missing ${marker}`)
  }

  if (count(html, /<link\s+rel=["']canonical["']/gi) !== 1) fail(`${localPath}: duplicate or missing canonical`)
  if (count(html, /<meta\s+property=["']og:image["']/gi) !== 1) fail(`${localPath}: duplicate or missing og:image`)
  if (titles.has(title)) fail(`${localPath}: duplicate title also used by ${titles.get(title)}`)
  else titles.set(title, localPath)

  console.log(`PASS ${localPath}`)
}

const robotsTxt = await readFile('robots.txt', 'utf8')
if (!/User-agent:\s*\*/i.test(robotsTxt) || !/Allow:\s*\//i.test(robotsTxt)) fail('robots.txt must allow public crawling')
if (!robotsTxt.includes(`Sitemap: ${SITE}/sitemap.xml`)) fail('robots.txt must reference the exact production sitemap')

const notFound = await readFile('404.html', 'utf8')
if (!/name=["']robots["']\s+content=["'][^"']*noindex[^"']*follow/i.test(notFound)) fail('404.html must be noindex,follow')

if (failed) process.exit(1)
console.log(`MyStocks SEO audit passed for ${urls.length} indexable pages.`)
