'use strict';

const fs = require('fs');
const path = require('path');

function normalizeId(value) {
  return value.replace(/\\/g, '/').replace(/\.md$/i, '');
}

function walkMarkdown(root) {
  if (!fs.existsSync(root)) return [];
  const out = [];
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else if (entry.isFile() && /\.md$/i.test(entry.name)) out.push(full);
    }
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function parseFrontMatter(text) {
  if (!text.startsWith('---')) return {};
  const end = text.indexOf('\n---', 3);
  if (end < 0) return {};
  const block = text.slice(3, end).trim();
  const result = {};
  for (const line of block.split(/\r?\n/)) {
    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (value.startsWith('[') && value.endsWith(']')) {
      value = value.slice(1, -1).split(',').map(v => v.trim().replace(/^['\"]|['\"]$/g, '')).filter(Boolean);
    } else {
      value = value.replace(/^['\"]|['\"]$/g, '');
    }
    result[match[1]] = value;
  }
  return result;
}

function titleFromMarkdown(text, fallback) {
  const match = text.match(/^#\s+(.+)$/m);
  return (match ? match[1] : fallback).trim();
}

function linksFromMarkdown(text) {
  const links = [];
  const wiki = /\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]/g;
  let match;
  while ((match = wiki.exec(text))) links.push(match[1].trim());

  const md = /\[[^\]]*\]\(([^)]+\.md)(?:#[^)]*)?\)/gi;
  while ((match = md.exec(text))) links.push(match[1].trim());
  return [...new Set(links)];
}

function inferType(relative, frontMatter) {
  if (frontMatter.type) return String(frontMatter.type).toLowerCase();
  const parts = normalizeId(relative).split('/');
  if (parts.length > 1) return parts[0].toLowerCase();
  if (/index|jarvis/i.test(parts[0])) return 'core';
  return 'memory';
}

function parseTags(frontMatter, text) {
  const tags = new Set();
  const fm = frontMatter.tags;
  if (Array.isArray(fm)) fm.forEach(tag => tags.add(String(tag).replace(/^#/, '').toLowerCase()));
  else if (typeof fm === 'string') fm.split(/[ ,]+/).filter(Boolean).forEach(tag => tags.add(tag.replace(/^#/, '').toLowerCase()));

  for (const match of text.matchAll(/(^|\s)#([\p{L}\p{N}_-]+)/gu)) tags.add(match[2].toLowerCase());
  return [...tags];
}

function scanBrain(root) {
  const files = walkMarkdown(root);
  const records = files.map(file => {
    const text = fs.readFileSync(file, 'utf8');
    const relative = path.relative(root, file).replace(/\\/g, '/');
    const id = normalizeId(relative);
    const frontMatter = parseFrontMatter(text);
    return {
      id,
      name: titleFromMarkdown(text, path.basename(id)),
      type: inferType(relative, frontMatter),
      tags: parseTags(frontMatter, text),
      file,
      relative,
      rawLinks: linksFromMarkdown(text),
      updatedAt: fs.statSync(file).mtimeMs
    };
  });

  const alias = new Map();
  for (const record of records) {
    const candidates = [record.id, record.name, path.basename(record.id), record.relative, normalizeId(record.relative)];
    for (const candidate of candidates) alias.set(String(candidate).toLowerCase(), record.id);
  }

  const links = [];
  const seen = new Set();
  for (const record of records) {
    for (const raw of record.rawLinks) {
      const normalized = normalizeId(raw).replace(/^\.\//, '');
      const target = alias.get(normalized.toLowerCase()) || alias.get(path.basename(normalized).toLowerCase());
      if (!target || target === record.id) continue;
      const key = `${record.id}->${target}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ source: record.id, target });
    }
  }

  const degrees = new Map(records.map(r => [r.id, 0]));
  for (const link of links) {
    degrees.set(link.source, (degrees.get(link.source) || 0) + 1);
    degrees.set(link.target, (degrees.get(link.target) || 0) + 1);
  }

  const nodes = records.map(record => ({
    id: record.id,
    name: record.name,
    type: record.type,
    tags: record.tags,
    relative: record.relative,
    degree: degrees.get(record.id) || 0,
    updatedAt: record.updatedAt
  }));

  return {
    nodes,
    links,
    stats: {
      neurons: nodes.length,
      synapses: links.length,
      types: [...new Set(nodes.map(n => n.type))].length,
      updatedAt: Date.now()
    }
  };
}

function radarEntries(root, filter) {
  const graph = scanBrain(root);
  const needle = (filter || '').toLowerCase();
  return graph.nodes
    .filter(node => {
      if (!needle) return node.type === 'radar' || node.tags.includes('radar');
      return node.name.toLowerCase().includes(needle) || node.id.toLowerCase().includes(needle) || node.tags.includes(needle);
    })
    .map((node, index) => ({
      ...node,
      strength: Math.max(0.25, Math.min(1, 0.42 + node.degree * 0.1 + ((index * 37) % 30) / 100))
    }));
}

module.exports = { scanBrain, radarEntries };
