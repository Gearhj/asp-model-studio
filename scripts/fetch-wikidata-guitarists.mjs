import { writeFile } from "node:fs/promises";

const endpoint = "https://query.wikidata.org/sparql";
const outputPath = new URL("../src/data/wikidataGuitarists.ts", import.meta.url);

const styleKeywords = {
  Rock: ["rock", "punk", "new wave", "psychedelic", "progressive", "alternative", "grunge", "garage"],
  Blues: ["blues", "rhythm and blues", "r&b", "soul"],
  Jazz: ["jazz", "bebop", "swing", "fusion", "gypsy jazz", "smooth jazz"],
  Country: ["country", "bluegrass", "americana", "folk", "honky-tonk", "western swing"],
  Metal: ["metal", "thrash", "doom", "black metal", "death metal", "heavy metal", "metalcore", "progressive metal"],
  Classical: ["classical", "flamenco", "romantic music", "baroque", "renaissance music"],
};

const styleOverrides = new Map(
  Object.entries({
    "Ace Frehley": ["Rock", "Metal"],
    "Adrian Belew": ["Rock"],
    "Adrian Smith": ["Metal", "Rock"],
    "Adrian Vandenberg": ["Rock"],
    "Al Di Meola": ["Jazz"],
    "Alex Skolnick": ["Metal", "Jazz"],
    "Albert Collins": ["Blues"],
    "Albert King": ["Blues"],
    "Albert Lee": ["Country", "Rock"],
    "Alex Lifeson": ["Rock"],
    "Allan Holdsworth": ["Jazz", "Rock"],
    "Ana Popović": ["Blues", "Rock"],
    "Andrés Segovia": ["Classical"],
    "Andy Summers": ["Rock"],
    "Angus Young": ["Rock"],
    "B.B. King": ["Blues"],
    "Barney Kessel": ["Jazz"],
    "Bert Jansch": ["Country", "Rock"],
    "Billy Gibbons": ["Rock", "Blues"],
    "Billy Corgan": ["Rock"],
    "Billy Strings": ["Country"],
    "Bo Diddley": ["Rock", "Blues"],
    "Bonnie Raitt": ["Blues", "Rock", "Country"],
    "Brad Paisley": ["Country"],
    "Brent Mason": ["Country"],
    "Brian May": ["Rock"],
    "Brian Setzer": ["Rock", "Blues"],
    "Buddy Guy": ["Blues"],
    "Buckethead": ["Rock", "Metal"],
    "Carlos Santana": ["Rock", "Blues"],
    "Charlie Byrd": ["Jazz", "Classical"],
    "Charlie Christian": ["Jazz"],
    "Chet Atkins": ["Country", "Jazz"],
    "Clarence White": ["Country", "Rock"],
    "Christopher Parkening": ["Classical"],
    "Chuck Berry": ["Rock", "Blues"],
    "Danny Gatton": ["Country", "Blues"],
    "Dave Davies": ["Rock"],
    "Dave Mustaine": ["Metal"],
    "David Gilmour": ["Rock"],
    "Derek Trucks": ["Blues", "Rock"],
    "Dick Dale": ["Rock"],
    "Dimebag Darrell": ["Metal", "Rock"],
    "Django Reinhardt": ["Jazz"],
    "Doc Watson": ["Country", "Blues"],
    "Don Rich": ["Country"],
    "Duane Allman": ["Rock", "Blues"],
    "Duane Eddy": ["Rock", "Country"],
    "Eddie Van Halen": ["Rock", "Metal"],
    "Ed O'Brien": ["Rock"],
    "Eldon Shamblin": ["Country", "Jazz"],
    "Emily Remler": ["Jazz"],
    "Eric Clapton": ["Blues", "Rock"],
    "Eric Johnson": ["Rock", "Blues"],
    "Frank Zappa": ["Rock", "Jazz"],
    "Freddie King": ["Blues"],
    "Gábor Szabó": ["Jazz"],
    "Gary Moore": ["Blues", "Rock", "Metal"],
    "Gary Clark Jr.": ["Blues", "Rock"],
    "George Benson": ["Jazz"],
    "George Harrison": ["Rock"],
    "George Lynch": ["Metal", "Rock"],
    "Glen Campbell": ["Country", "Rock"],
    "Glenn Tipton": ["Metal", "Rock"],
    "Graham Coxon": ["Rock"],
    "Grant Green": ["Jazz"],
    "Hank Marvin": ["Rock"],
    "Herman Li": ["Metal"],
    "Hubert Sumlin": ["Blues"],
    "J Mascis": ["Rock"],
    "Jack White": ["Rock", "Blues"],
    "James Burton": ["Country", "Rock"],
    "James Hetfield": ["Metal", "Rock"],
    "Jake E. Lee": ["Metal", "Rock"],
    "Jeff Beck": ["Rock", "Jazz", "Blues"],
    "Jeff Hanneman": ["Metal"],
    "Jerry Garcia": ["Rock", "Country"],
    "Jerry Cantrell": ["Rock", "Metal"],
    "Jerry Reed": ["Country"],
    "Jimi Hendrix": ["Rock", "Blues"],
    "Jimmy Page": ["Rock", "Blues"],
    "Jim Hall": ["Jazz"],
    "Joe Bonamassa": ["Blues", "Rock"],
    "Joe Pass": ["Jazz"],
    "Joe Perry": ["Rock", "Blues"],
    "Joe Satriani": ["Rock", "Metal"],
    "John 5": ["Metal", "Country"],
    "John Fahey": ["Country", "Blues"],
    "John Frusciante": ["Rock"],
    "John McLaughlin": ["Jazz", "Rock"],
    "John Petrucci": ["Metal", "Rock"],
    "John Scofield": ["Jazz"],
    "John Williams": ["Classical"],
    "Johnny Marr": ["Rock"],
    "Johnny Ramone": ["Rock"],
    "Jonny Greenwood": ["Rock"],
    "Julian Lage": ["Jazz"],
    "Julian Bream": ["Classical"],
    "Junior Brown": ["Country"],
    "Kenny Burrell": ["Jazz"],
    "Kenny Wayne Shepherd": ["Blues", "Rock"],
    "Keith Richards": ["Rock", "Blues"],
    "Kerry King": ["Metal"],
    "Kim Thayil": ["Rock", "Metal"],
    "Kirk Hammett": ["Metal", "Rock"],
    "K.K. Downing": ["Metal", "Rock"],
    "Kurt Cobain": ["Rock"],
    "Larry Carlton": ["Jazz", "Rock"],
    "Lee Ritenour": ["Jazz"],
    "Lenny Breau": ["Jazz", "Country"],
    "Les Paul": ["Jazz", "Country"],
    "Lindsey Buckingham": ["Rock"],
    "Link Wray": ["Rock"],
    "Lowell George": ["Rock", "Blues"],
    "Luther Perkins": ["Country"],
    "Mark Knopfler": ["Rock", "Country"],
    "Mark Tremonti": ["Rock", "Metal"],
    "Marty Friedman": ["Metal", "Rock"],
    "Maybelle Carter": ["Country"],
    "Merle Travis": ["Country"],
    "Michael Schenker": ["Rock", "Metal"],
    "Mike McCready": ["Rock"],
    "Mike Stern": ["Jazz", "Rock"],
    "Mick Ronson": ["Rock"],
    "Mick Taylor": ["Rock", "Blues"],
    "Mike Bloomfield": ["Blues", "Rock"],
    "Misha Mansoor": ["Metal"],
    "Molly Tuttle": ["Country"],
    "Nancy Wilson": ["Rock"],
    "Narciso Yepes": ["Classical"],
    "Neal Schon": ["Rock"],
    "Nile Rodgers": ["Rock"],
    "Nuno Bettencourt": ["Rock", "Metal"],
    "Paco de Lucía": ["Classical", "Jazz"],
    "Pat Metheny": ["Jazz"],
    "Pat Martino": ["Jazz"],
    "Paul Gilbert": ["Rock", "Metal"],
    "Pepe Romero": ["Classical"],
    "Pete Townshend": ["Rock"],
    "Peter Green": ["Blues", "Rock"],
    "Phil Collen": ["Rock", "Metal"],
    "Prince": ["Rock", "Blues"],
    "Randy Rhoads": ["Metal", "Rock"],
    "Richard Thompson": ["Rock", "Country"],
    "Richie Sambora": ["Rock"],
    "Ritchie Blackmore": ["Rock", "Metal"],
    "Robert Fripp": ["Rock"],
    "Robert Johnson": ["Blues"],
    "Robbie Robertson": ["Rock"],
    "Rory Gallagher": ["Blues", "Rock"],
    "Roy Buchanan": ["Blues", "Country"],
    "Roy Clark": ["Country"],
    "Ry Cooder": ["Blues", "Country"],
    "Samantha Fish": ["Blues", "Rock"],
    "Scotty Moore": ["Rock", "Country"],
    "Sharon Isbin": ["Classical"],
    "Slash": ["Rock", "Metal"],
    "Stanley Jordan": ["Jazz"],
    "Steve Cropper": ["Blues", "Rock"],
    "Steve Cropper": ["Blues", "Rock"],
    "Steve Howe": ["Rock"],
    "Steve Lukather": ["Rock", "Jazz"],
    "Steve Morse": ["Rock", "Country"],
    "Steve Vai": ["Rock", "Metal"],
    "Stevie Ray Vaughan": ["Blues", "Rock"],
    "Stone Gossard": ["Rock"],
    "Susan Tedeschi": ["Blues", "Rock"],
    "T-Bone Walker": ["Blues"],
    "Tal Farlow": ["Jazz"],
    "Terry Kath": ["Rock"],
    "The Edge": ["Rock"],
    "Thurston Moore": ["Rock"],
    "Tom Morello": ["Rock", "Metal"],
    "Tom Scholz": ["Rock"],
    "Tommy Emmanuel": ["Country"],
    "Tony Iommi": ["Metal", "Rock"],
    "Tosin Abasi": ["Metal"],
    "Uli Jon Roth": ["Rock", "Metal"],
    "Vernon Reid": ["Rock", "Metal"],
    "Vince Gill": ["Country"],
    "Vivian Campbell": ["Rock", "Metal"],
    "Warren DeMartini": ["Rock", "Metal"],
    "Wes Montgomery": ["Jazz"],
    "Yngwie Malmsteen": ["Metal", "Rock"],
    "Zakk Wylde": ["Metal", "Rock"],
  }).map(([name, styles]) => [name.toLowerCase(), styles]),
);

function buildQuery(limit, offset) {
  return `
SELECT DISTINCT ?person ?personLabel ?birthDate ?deathDate
       ?sitelinks
WHERE {
  ?person wdt:P31 wd:Q5.
  ?person wdt:P106/wdt:P279* wd:Q855091.
  ?person wikibase:sitelinks ?sitelinks.
  ?person rdfs:label ?personLabel.
  FILTER(LANG(?personLabel) = "en")
  FILTER(?sitelinks >= 8)
  OPTIONAL { ?person wdt:P569 ?birthDate. }
  OPTIONAL { ?person wdt:P570 ?deathDate. }
}
ORDER BY DESC(?sitelinks) ?personLabel
LIMIT ${limit}
OFFSET ${offset}
`;
}

function yearFromDate(value, fallback) {
  if (!value) return fallback;
  const match = String(value).match(/^-?\d{1,4}/);
  return match ? Number(match[0]) : fallback;
}

function inferStyles(name, genresText) {
  const override = styleOverrides.get(name.toLowerCase());
  if (override) return override;

  const haystack = genresText.toLowerCase();
  const styles = Object.entries(styleKeywords)
    .filter(([, keywords]) => keywords.some((keyword) => haystack.includes(keyword)))
    .map(([style]) => style);

  return styles.length ? styles : ["Unclassified"];
}

function scoreFromStyles(styles, activeFrom, activeTo) {
  const careerYears = Math.max(1, activeTo - activeFrom);
  const longevity = Math.max(16, Math.min(82, Math.round(careerYears * 1.5)));
  const base = styles.includes("Jazz") || styles.includes("Metal") || styles.includes("Classical") ? 52 : 46;
  return {
    pollScore: 22,
    influence: base,
    technique: styles.includes("Jazz") || styles.includes("Metal") || styles.includes("Classical") ? 62 : 50,
    innovation: base,
    commercial: 38,
    longevity,
  };
}

function slugify(value) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function cleanString(value, fallback) {
  const first = String(value ?? "")
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean)[0];
  return first || fallback;
}

function toGuitarist(binding) {
  const name = binding.personLabel.value;
  const genres = binding.genres?.value ?? "";
  const styles = inferStyles(name, genres);
  const birthYear = yearFromDate(binding.birthDate?.value, 1975);
  const deathYear = yearFromDate(binding.deathDate?.value, 2026);
  const activeFrom = Math.max(1900, Math.min(2026, birthYear + 18));
  const activeTo = Math.max(activeFrom, Math.min(2026, deathYear || 2026));
  const scores = scoreFromStyles(styles, activeFrom, activeTo);

  return {
    id: `wd-${slugify(name)}`,
    name,
    styles,
    primaryStyle: styles[0],
    country: cleanString(binding.countries?.value, "Unknown"),
    activeFrom,
    activeTo,
    bands: ["Catalog import"],
    ...scores,
    signature: `Notability-ranked Wikidata import with ${binding.sitelinks?.value ?? "unknown"} sitelinks. Genres: ${genres || "not specified"}. Add curated poll evidence to improve scoring confidence.`,
  };
}

function hasReadableName(binding) {
  const label = binding.personLabel?.value ?? "";
  return label.length > 1 && !/^Q\d+$/.test(label);
}

function mergeBindingsByPerson(bindings) {
  const byPerson = new Map();
  for (const binding of bindings) {
    const key = binding.person.value;
    const current = byPerson.get(key) ?? { ...binding, genreValues: new Set(), countryValues: new Set() };
    if (binding.genreLabel?.value) current.genreValues.add(binding.genreLabel.value);
    if (binding.countryLabel?.value) current.countryValues.add(binding.countryLabel.value);
    if (Number(binding.sitelinks?.value ?? 0) > Number(current.sitelinks?.value ?? 0)) current.sitelinks = binding.sitelinks;
    byPerson.set(key, current);
  }

  return Array.from(byPerson.values()).map((binding) => ({
    ...binding,
    genres: { value: Array.from(binding.genreValues).join("|") },
    countries: { value: Array.from(binding.countryValues).join("|") },
  }));
}

function uniqueByName(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = item.name.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function serialize(items) {
  return `import type { Guitarist } from "./guitarists";

// Generated by scripts/fetch-wikidata-guitarists.mjs from Wikidata's SPARQL endpoint.
// Catalog-only scores are conservative defaults; curated ranking evidence should override them.
export const wikidataGuitarists: Guitarist[] = ${JSON.stringify(items, null, 2)};
`;
}

async function fetchPage(limit, offset) {
  const url = `${endpoint}?query=${encodeURIComponent(buildQuery(limit, offset))}&format=json`;
  const response = await fetch(url, {
    headers: {
      Accept: "application/sparql-results+json",
      "User-Agent": "GreatestGuitaristLab/0.1 (local data import)",
    },
  });

  if (!response.ok) {
    throw new Error(`Wikidata request failed at offset ${offset}: ${response.status} ${response.statusText}`);
  }

  const payload = await response.json();
  return payload.results.bindings;
}

const pageSize = 200;
const pages = 6;
const bindings = [];

for (let page = 0; page < pages; page += 1) {
  const offset = page * pageSize;
  const pageBindings = await fetchPage(pageSize, offset);
  bindings.push(...pageBindings);
  console.log(`Fetched ${pageBindings.length} rows at offset ${offset}`);
  if (pageBindings.length < pageSize) break;
}

const guitarists = uniqueByName(
  mergeBindingsByPerson(bindings)
    .filter(hasReadableName)
    .map(toGuitarist)
    .filter((guitarist) => !guitarist.styles.includes("Unclassified")),
);

await writeFile(outputPath, serialize(guitarists), "utf8");
console.log(`Wrote ${guitarists.length} Wikidata guitarists to ${outputPath.pathname}`);
