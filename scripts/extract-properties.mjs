import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const propsDir = path.join(root, 'Properties');
const propsHtmlPath = path.join(root, 'properties.html');

const propertyFiles = fs
  .readdirSync(propsDir)
  .filter((f) => f.toLowerCase().endsWith('.html'));

/** Basic helper to read text between simple tags */
const getText = (html, regex) => {
  const m = html.match(regex);
  return m ? m[1].replace(/\s+/g, ' ').trim() : null;
};

const bySlug = {};

for (const file of propertyFiles) {
  const full = path.join(propsDir, file);
  const html = fs.readFileSync(full, 'utf8');

  const slug = file.replace(/\.html$/i, '').replace(/\s+/g, '-');

  const title =
    getText(
      html,
      /<h1[^>]*class="[^"]*font-serif[^"]*"[^>]*>([\s\S]*?)<\/h1>/i,
    ) ?? slug;

  const location =
    getText(
      html,
      /<p class="text-xl[^"]*opacity-90[^"]*"[^>]*>([\s\S]*?)<\/p>/i,
    ) ?? '';

  const beds = getText(
    html,
    /<span class="font-medium">(\d+)\s*Beds<\/span>/i,
  );
  const baths = getText(
    html,
    /<span class="font-medium">(\d+)\s*Baths<\/span>/i,
  );
  const sleeps = getText(
    html,
    /<span class="font-medium">Sleeps\s*(\d+)<\/span>/i,
  );

  const desc = getText(
    html,
    /About this space<\/h3>[\s\S]*?<p[^>]*>([\s\S]*?)<\/p>/i,
  );

  const imagesMatch = html.match(
    /window\.propertyImages\s*=\s*\[([\s\S]*?)\];/i,
  );
  let photos = [];
  if (imagesMatch) {
    photos = imagesMatch[1]
      .split('\n')
      .map((line) => {
        const m = line.match(/'(.*?)'/);
        return m ? `Properties/${m[1]}` : null;
      })
      .filter(Boolean);
  }

  const heroImage = photos[0] ?? null;

  bySlug[slug] = {
    slug,
    title,
    location,
    beds: beds ? Number(beds) : null,
    baths: baths ? Number(baths) : null,
    sleeps: sleeps ? Number(sleeps) : null,
    viewType:
      location && location.includes('·')
        ? location.split('·')[1].trim()
        : null,
    description: desc,
    heroImage,
    photos,
    amenities: [],
    rating: null,
    reviewCount: null,
    featured: false,
    vrboUrl: null,
  };
}

// Enhance with list-page data (ratings, featured flags, hero images) from properties.html
if (fs.existsSync(propsHtmlPath)) {
  const listHtml = fs.readFileSync(propsHtmlPath, 'utf8');
  const cardRegex =
    /<div class="property-card[\s\S]*?<\/div>\s*<\/div>/gi;
  const cards = listHtml.match(cardRegex) || [];

  for (const card of cards) {
    const hrefMatch = card.match(
      /<a href="Properties\/([^"]+)\.html"[^>]*>/i,
    );
    if (!hrefMatch) continue;
    const slug = hrefMatch[1];
    const key = slug;
    if (!bySlug[key]) continue;

    const title = getText(
      card,
      /<h4 class="font-serif[^"]*"[^>]*>([\s\S]*?)<\/h4>/i,
    );
    const location = getText(
      card,
      /<p class="text-gray-500[^"]*"[^>]*>[\s\S]*?<span>([\s\S]*?)<\/span>/i,
    );

    const beds = getText(
      card,
      /<span class="font-medium">(\d+)\s*Beds<\/span>/i,
    );
    const baths = getText(
      card,
      /<span class="font-medium">(\d+)\s*Baths<\/span>/i,
    );
    const sleeps = getText(
      card,
      /<span class="font-medium">Sleeps\s*(\d+)<\/span>/i,
    );

    const rating = getText(
      card,
      /<span class="font-bold text-gray-900">([\d.]+)<\/span>/i,
    );
    const reviewCount = getText(
      card,
      /<span class="text-gray-500 text-sm">\((\d+)\s+reviews\)<\/span>/i,
    );

    const imgMatch = card.match(
      /<img src="([^"]+)"[^>]*class="property-image[^"]*"/i,
    );
    const heroImage = imgMatch ? imgMatch[1] : null;

    const existing = bySlug[key];
    if (!existing) continue;

    Object.assign(existing, {
      // prefer list-page title/location if present
      title: title || existing.title,
      location: location || existing.location,
      beds: beds ? Number(beds) : existing.beds,
      baths: baths ? Number(baths) : existing.baths,
      sleeps: sleeps ? Number(sleeps) : existing.sleeps,
      heroImage: heroImage || existing.heroImage,
      rating: rating ? Number(rating) : null,
      reviewCount: reviewCount ? Number(reviewCount) : null,
    });

    // Mark as featured if it appeared on the list page (can refine later)
    existing.featured = true;
  }
}

const properties = Object.values(bySlug).sort((a, b) =>
  a.title.localeCompare(b.title),
);

const out = `const properties = ${JSON.stringify(
  properties,
  null,
  2,
)};\n\nexport default properties;\n`;

fs.mkdirSync(path.join(root, 'src', 'data'), { recursive: true });
fs.writeFileSync(
  path.join(root, 'src', 'data', 'properties.js'),
  out,
  'utf8',
);

console.log('Extracted', properties.length, 'properties to src/data/properties.js');

