let canvas, ctx, isDrawing = false;
let color = '#d81b60';

function initCanvas(canvasId) {
    canvas = document.getElementById(canvasId);
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.min(400, rect.width - 40);
    canvas.height = 200;

    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#f8bbd0';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, canvas.width, canvas.height);

    canvas.onmousedown = startDraw;
    canvas.onmousemove = draw;
    canvas.onmouseup = stopDraw;
    canvas.onmouseleave = stopDraw;
    canvas.ontouchstart = function (e) { e.preventDefault(); startDraw(e.touches[0]); };
    canvas.ontouchmove = function (e) { e.preventDefault(); draw(e.touches[0]); };
    canvas.ontouchend = stopDraw;
}

function pos(e) {
    const r = canvas.getBoundingClientRect();
    return {
        x: (e.offsetX !== undefined ? e.offsetX : e.clientX - r.left),
        y: (e.offsetY !== undefined ? e.offsetY : e.clientY - r.top)
    };
}

function startDraw(e) {
    isDrawing = true;
    const p = pos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
}

function draw(e) {
    if (!isDrawing) return;
    const p = pos(e);
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.strokeStyle = color;
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
}

function stopDraw() {
    isDrawing = false;
    ctx.beginPath();
}

function setDrawColor(c) {
    color = c;
}

function clearCanvas() {
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#f8bbd0';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, canvas.width, canvas.height);
    document.getElementById('drawing-input').value = '';
}

function saveDrawing() {
    document.getElementById('drawing-input').value = canvas.toDataURL('image/png');
}

function toggleCanvas() {
    const c = document.getElementById('draw-canvas');
    const b = document.getElementById('canvas-tools');
    const h = document.getElementById('canvas-hint');
    const show = c.style.display === 'none';
    c.style.display = show ? 'block' : 'none';
    b.style.display = show ? 'flex' : 'none';
    if (h) h.style.display = 'none';
    if (show) initCanvas('draw-canvas');
}
