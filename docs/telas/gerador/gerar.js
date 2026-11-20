// Gera SVGs das telas a partir do mockup v3, prontos para o ImageMagick.
// Uso: node gerar.js docs/telas-mio-v3.html <pasta> "DejaVu Sans"
//      for f in <pasta>/*.svg; do convert -density 192 -background none "$f" "${f%.svg}.png"; done
// O ImageMagick nao entende letter-spacing nem polyline com fill: o script ja ajusta.
const fs = require("fs");
const [html, saida, fonte] = process.argv.slice(2);
let js = fs.readFileSync(html, "utf8").split("<script>")[1].split("</script>")[0];
js = js.split("// ---------- simulador")[0];               // so as telas, sem DOM
js = js.replace('const F = "Rajdhani, Tahoma, Verdana, sans-serif";', `const F = "${fonte}";`);
const f = new Function(js + "\nreturn { TELAS, setNivel: v => { nivel = v; } };");
const { TELAS, setNivel } = f();

const limpar = svg => svg
  .replace(/ letter-spacing="[^"]*"/g, "")
  .replace(/<polyline points="([^"]*)"/g, (_, p) => `<path d="M ${p.trim().split(/\s+/).join(" L ")}"`);

const nomes = ["1-internet", "2-conexao", "3-servidor", "4-maquinas", "5-servicos",
               "6-seguranca", "7-sistema", "8-alerta"];
const gravar = (nome, corpo) => fs.writeFileSync(`${saida}/${nome}.svg`,
  `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">${limpar(corpo)}</svg>`);

TELAS.forEach((t, k) => {
  setNivel(0);
  gravar(nomes[k], t.svg(k < 7 ? k : -1, 0.45));
});
// variantes: alerta ambar (aviso) e conexao com DNS falhando
setNivel(1);
gravar("9-alerta-aviso", TELAS[7].svg(-1, 0.45));
gravar("2b-conexao-dns", TELAS[1].svg(1, 0.45));
setNivel(0);
console.log("ok", TELAS.length + 2);
