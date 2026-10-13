/* Door drawing geometry. Open/closed and obstruction decisions come from backend. */
window.CampusDoors = {
  isDoor(o) {return o?.type==='glass-door'||(o?.type==='sliding-door'&&o.interactiveDoor===true);},
  leaf(door,open=door.open) {
    const horizontal=door.orientation==='horizontal',length=horizontal?door.w:door.h;
    const shift=door.type==='sliding-door'&&open?(length+6)*(door.slide||1):0;
    const start={x:door.x+(horizontal?shift:door.w/2),y:door.y+(horizontal?door.h/2:shift)};
    if(door.type==='sliding-door')return {start,end:{x:start.x+(horizontal?length:0),y:start.y+(horizontal?0:length)},dx:horizontal?length:0,dy:horizontal?0:length,thickness:horizontal?door.h:door.w};
    const dx=open?(horizontal?0:door.swing*length):(horizontal?length:0);
    const dy=open?(horizontal?door.swing*length:0):(horizontal?0:length);
    return {start,end:{x:start.x+dx,y:start.y+dy},dx,dy,thickness:horizontal?door.h:door.w};
  },
  footprint(door,open=door.open) {
    const {start,end,dx,dy,thickness}=this.leaf(door,open);
    return {x:Math.min(start.x,end.x)-(dy?thickness/2:0),y:Math.min(start.y,end.y)-(dx?thickness/2:0),w:Math.abs(dx)+(dy?thickness:0),h:Math.abs(dy)+(dx?thickness:0)};
  },
  bounds(door) {
    const opening=this.footprint(door,false),leaf=this.footprint(door,door.type==='sliding-door'?true:door.open);
    const x=Math.min(opening.x,leaf.x),y=Math.min(opening.y,leaf.y);
    return {x,y,w:Math.max(opening.x+opening.w,leaf.x+leaf.w)-x,h:Math.max(opening.y+opening.h,leaf.y+leaf.h)-y};
  },
};
