// Cari teks Bahasa Indonesia yang akan tampil apa adanya saat bahasa = English.
//
//   npm run check:i18n            -> daftar temuan, exit 1 bila ada
//
// Teks dianggap Bahasa Indonesia bila memuat kata penanda (MARKERS). Teks lolos bila:
//   - ada di kamus src/i18n/en.js (komponen/t() menerjemahkannya), DAN
//   - tidak ditulis mentah sebagai teks JSX / atribut JSX tanpa t() di komponen yang tidak menerjemahkan.
// Abaikan satu baris dengan komentar `i18n-ignore` (mis. contoh input Bahasa Indonesia untuk chatbot).
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from '@babel/parser';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'src');
const EN = (await import(join(SRC, 'i18n', 'en.js'))).default;

const MARKERS = /\b(yang|tidak|dan|untuk|dengan|belum|sudah|batal|kembali|simpan|hapus|tambah|dibuat|ditutup|dibatalkan|pilih|misi|tenggat|gagal|berhasil|menunggu|lanjut|tutup|buka|kirim|ditemukan|harus|semua|baru|pesan|percakapan|persetujuan|pengaturan|ubah|lihat|muat|memuat|sedang|bila|atau|dari|ke|di|ini|itu|akan|bisa|dapat|tanpa|sebelum|setelah|jadwal|stok|tanggal|jumlah|harga|nama|satuan|keterangan|catatan|terima|tolak|setujui|diterima|ditolak|disetujui|kosong|wajib|minimal|maksimal|hari|minggu|bulan|tahun|sekarang|terakhir|selesai|aktif|nonaktif|ya|mohon|silakan|coba|lagi|kesalahan|terhubung|ringkasan|rincian|detail barang|pengguna|bahasa|tema|gelap|terang|riwayat|semua|cari|urutkan|unduh|cetak|salin|tersalin|perlu|butuh|kurang|lebih|sisa|dipesan|diproduksi|produksi|pemasok|pesanan|pembelian|penerimaan|barang)\b/i;

const files = [];
(function walk(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) { if (f !== 'i18n') walk(p); } else if (/\.(jsx?|mjs)$/.test(f)) files.push(p);
  }
})(SRC);

const isTCall = (node) => node?.type === 'CallExpression' && ['t', 'tx'].includes(node.callee?.name);
const findings = [];

for (const file of files) {
  const code = readFileSync(file, 'utf8');
  const lines = code.split('\n');
  let ast;
  try {
    ast = parse(code, { sourceType: 'module', plugins: ['jsx'] });
  } catch (e) {
    findings.push({ file, line: 0, text: `PARSE ERROR ${e.message}` });
    continue;
  }
  const report = (node, text, why) => {
    const line = node.loc.start.line;
    if (/i18n-ignore/.test(lines[line - 1] ?? '') || /i18n-ignore/.test(lines[line - 2] ?? '')) return;
    findings.push({ file, line, text, why });
  };
  (function visit(node, parent, key) {
    if (!node || typeof node.type !== 'string') return;
    if (node.type === 'ImportDeclaration' || node.type === 'ExportAllDeclaration') return;
    let text = null;
    if (node.type === 'StringLiteral') text = node.value;
    else if (node.type === 'TemplateLiteral') text = node.quasis.map((q) => q.value.cooked).join('{…}');
    else if (node.type === 'JSXText') text = node.value.replace(/\s+/g, ' ').trim();
    if (text && MARKERS.test(text) && /[a-z]{2}/i.test(text)) {
      const wrapped = isTCall(parent) && key === 'arguments';
      const isPropKey = parent?.type === 'ObjectProperty' && key === 'key';
      const isClass = parent?.type === 'JSXAttribute' && ['className', 'type', 'name', 'id', 'to', 'href'].includes(parent.name?.name);
      if (!isPropKey && !isClass) {
        if (node.type === 'TemplateLiteral' && !wrapped) report(node, text, 'template literal (pakai t() dengan {var})');
        else if (node.type === 'JSXText') report(node, text, 'teks JSX mentah (bungkus dengan {t(...)})');
        else if (!(text in EN)) report(node, text, wrapped ? 'belum ada di en.js' : 'belum di en.js / tanpa t()');
      }
    }
    for (const [k, v] of Object.entries(node)) {
      if (k === 'loc' || k === 'start' || k === 'end' || k === 'extra' || k === 'leadingComments' || k === 'trailingComments') continue;
      if (Array.isArray(v)) v.forEach((c) => visit(c, node, k));
      else if (v && typeof v.type === 'string') visit(v, node, k);
    }
  })(ast.program, null, null);
}

for (const f of findings) console.log(`${relative(ROOT, f.file)}:${f.line}  ${JSON.stringify(f.text)}  — ${f.why}`);
console.log(`\n${findings.length} temuan`);
process.exit(findings.length ? 1 : 0);
