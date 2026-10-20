import type { Point } from '../api/annotation'

const EPS = 1e-9
const cross = (a: Point, b: Point, p: Point) => (b.x-a.x)*(p.y-a.y)-(b.y-a.y)*(p.x-a.x)
function onSegment(p: Point, a: Point, b: Point) {
  return Math.abs(cross(a,b,p)) <= EPS &&
    p.x >= Math.min(a.x,b.x)-EPS && p.x <= Math.max(a.x,b.x)+EPS &&
    p.y >= Math.min(a.y,b.y)-EPS && p.y <= Math.max(a.y,b.y)+EPS
}

/** 包含边界；用于实际轮廓命中，避免旋转框的外接矩形误选。 */
export function pointInPolygon(p: Point, polygon: Point[]) {
  let inside = false
  for (let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
    const a=polygon[j],b=polygon[i]
    if (onSegment(p,a,b)) return true
    if ((a.y>p.y)!==(b.y>p.y) && p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) inside=!inside
  }
  return inside
}

function segmentsIntersect(a: Point,b: Point,c: Point,d: Point) {
  const abC=cross(a,b,c),abD=cross(a,b,d),cdA=cross(c,d,a),cdB=cross(c,d,b)
  return ((abC>EPS && abD<-EPS || abC<-EPS && abD>EPS) &&
    (cdA>EPS && cdB<-EPS || cdA<-EPS && cdB>EPS)) ||
    onSegment(c,a,b) || onSegment(d,a,b) || onSegment(a,c,d) || onSegment(b,c,d)
}

/** 框选碰到轮廓即选中，包括边相交和框选区域完全落在对象内部。 */
export function polygonIntersectsRect(polygon: Point[], start: Point, end: Point) {
  const left=Math.min(start.x,end.x),right=Math.max(start.x,end.x)
  const top=Math.min(start.y,end.y),bottom=Math.max(start.y,end.y)
  if (polygon.some(p=>p.x>=left && p.x<=right && p.y>=top && p.y<=bottom)) return true
  const corners=[{x:left,y:top},{x:right,y:top},{x:right,y:bottom},{x:left,y:bottom}]
  if (corners.some(p=>pointInPolygon(p,polygon))) return true
  return polygon.some((a,i)=>corners.some((c,j)=>
    segmentsIntersect(a,polygon[(i+1)%polygon.length],c,corners[(j+1)%4])))
}

/** 限制整组位移，不逐点裁剪，保持每个对象形状及彼此间距。 */
export function clampGroupDelta(polygons: Point[][], delta: Point): Point {
  let minX=1,minY=1,maxX=0,maxY=0
  for (const polygon of polygons) for (const p of polygon) {
    minX=Math.min(minX,p.x);minY=Math.min(minY,p.y)
    maxX=Math.max(maxX,p.x);maxY=Math.max(maxY,p.y)
  }
  return {x:Math.max(-minX,Math.min(1-maxX,delta.x)),y:Math.max(-minY,Math.min(1-maxY,delta.y))}
}
