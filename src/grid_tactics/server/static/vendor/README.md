# Vendored browser dependencies

- `socket.io-4.7.4.min.js` — official Socket.IO browser client v4.7.4,
  vendored from `https://cdn.socket.io/4.7.4/socket.io.min.js` so local and
  privacy-filtered browsers can initialize the game without a third-party
  request. The upstream MIT notice is retained in the file header.
- SHA-256: `AD52FC540680945FE7549C0F1B1126B54029DD7EB25F8CE2B079A6242C807011`

When upgrading, replace the artifact, update the versioned script path in
`../game.html`, and update the checksum above.
