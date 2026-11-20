// Gera SVGs das telas a partir do mockup. Uso: node gerar.js docs/telas-mio-v2.html <pasta> "DejaVu Sans"
// Depois: tirar letter-spacing, trocar polyline por path e converter com ImageMagick (convert -density 192).
const fs = require("fs");
const [html, saida, fonte] = process.argv.slice(2);
let js = fs.readFileSync(html, "utf8").split("<script>")[1].split("</script>")[0];
js = js.split("// ---------- simulador")[0];               // so as telas, sem DOM
js = js.replace('const F = "Rajdhani, Tahoma, Verdana, sans-serif";', `const F = "${fonte}";`);
const f = new Function(js + "\nreturn { TELAS, setAlerta: v => { alerta = v; } };");
const { TELAS, setAlerta } = f();
const nomes = ["1-internet", "2-servidor", "3-maquinas", "4-servicos", "5-alerta"];
TELAS.forEach((t, k) => {
  setAlerta(false);
  const corpo = t.svg(Math.min(k, 3), 0.45);
  fs.writeFileSync(`${saida}/${nomes[k]}.svg`,
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">${corpo}</svg>`);
});
console.log("ok", TELAS.length);
