/* Door geometry uses the same floor coordinates as collision and movement. */
window.CampusDoors = {
  leaf(door,open=door.open) {
    const horizontal=door.orientation==='horizontal',length=horizontal?door.w:door.h;
    const start={x:door.x+(horizontal?0:door.w/2),y:door.y+(horizontal?door.h/2:0)};
    const dx=open?(horizontal?0:door.swing*length):(horizontal?length:0);
    const dy=open?(horizontal?door.swing*length:0):(horizontal?0:length);
    return {start,end:{x:start.x+dx,y:start.y+dy},dx,dy,thickness:horizontal?door.h:door.w};
  },
  footprint(door,open=door.open) {
    const {start,end,dx,dy,thickness}=this.leaf(door,open);
    return {x:Math.min(start.x,end.x)-(dy?thickness/2:0),y:Math.min(start.y,end.y)-(dx?thickness/2:0),w:Math.abs(dx)+(dy?thickness:0),h:Math.abs(dy)+(dx?thickness:0)};
  },
  bounds(door) {
    const opening=this.footprint(door,false),leaf=this.footprint(door);
    const x=Math.min(opening.x,leaf.x),y=Math.min(opening.y,leaf.y);
    return {x,y,w:Math.max(opening.x+opening.w,leaf.x+leaf.w)-x,h:Math.max(opening.y+opening.h,leaf.y+leaf.h)-y};
  },
  distance(door,x,y) {
    const distance=r=>Math.hypot(Math.max(r.x-x,0,x-r.x-r.w),Math.max(r.y-y,0,y-r.y-r.h));
    return Math.min(distance(this.footprint(door,false)),distance(this.footprint(door)));
  },
  blocked(door,open,actors,radius=6) {
    const r=this.footprint(door,open);
    return actors.some(actor=>(!actor.floor||actor.floor==='campus')&&Math.hypot(Math.max(r.x-actor.x,0,actor.x-r.x-r.w),Math.max(r.y-actor.y,0,actor.y-r.y-r.h))<radius);
  },
};
