/* Small collision-aware navigation engine. No server or external library needed. */
window.CampusNavigation = {
  create({width,height,isWalkable,step=6}) {
    const cols=Math.ceil(width/step),rows=Math.ceil(height/step),size=cols*rows;
    let open=null;
    const point=id=>({x:(id%cols)*step,y:Math.floor(id/cols)*step});
    function init(){if(open)return;open=new Uint8Array(size);for(let id=0;id<size;id++){const p=point(id);open[id]=isWalkable(p.x,p.y)?1:0;}}
    function nearest(p){
      let best=-1,d=Infinity;const gx=Math.round(p.x/step),gy=Math.round(p.y/step);
      for(let ring=0;ring<13;ring++){
        for(let y=gy-ring;y<=gy+ring;y++)for(let x=gx-ring;x<=gx+ring;x++){
          if(x<0||y<0||x>=cols||y>=rows||Math.max(Math.abs(x-gx),Math.abs(y-gy))!==ring)continue;
          const id=y*cols+x;if(!open[id])continue;const q=point(id),dist=Math.hypot(q.x-p.x,q.y-p.y);if(dist<d&&clear(p,q)){d=dist;best=id;}
        }if(best>=0&&ring*step>d+step)return best;
      }return best;
    }
    function clear(a,b){const d=Math.hypot(a.x-b.x,a.y-b.y),n=Math.ceil(d/2);for(let i=0;i<=n;i++){const t=n?i/n:0;if(!isWalkable(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t))return false;}return true;}
    function route(start,end){
      init();if(!isWalkable(start.x,start.y)||!isWalkable(end.x,end.y))return null;
      if(clear(start,end))return [end];
      const from=nearest(start),to=nearest(end);if(from<0||to<0)return null;
      const scores=new Float32Array(size);scores.fill(Infinity);const parent=new Int32Array(size);parent.fill(-1);const closed=new Uint8Array(size),heap=[];
      const goal=point(to),heuristic=id=>{const p=point(id);return Math.hypot(p.x-goal.x,p.y-goal.y)/step;};
      function push(id,score){let i=heap.length;heap.push({id,score});while(i>0){const j=(i-1)>>1;if(heap[j].score<=score)break;heap[i]=heap[j];i=j;}heap[i]={id,score};}
      function pop(){const first=heap[0],last=heap.pop();if(heap.length){let i=0;while(true){let j=i*2+1;if(j>=heap.length)break;if(j+1<heap.length&&heap[j+1].score<heap[j].score)j++;if(last.score<=heap[j].score)break;heap[i]=heap[j];i=j;}heap[i]=last;}return first.id;}
      scores[from]=0;push(from,heuristic(from));
      const dirs=[[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]];
      let reached=false;
      while(heap.length){const id=pop();if(closed[id])continue;closed[id]=1;if(id===to){reached=true;break;}const x=id%cols,y=Math.floor(id/cols);
        for(const [dx,dy] of dirs){const xx=x+dx,yy=y+dy;if(xx<0||yy<0||xx>=cols||yy>=rows)continue;const next=yy*cols+xx;if(!open[next]||closed[next])continue;if(dx&&dy&&(!open[y*cols+xx]||!open[yy*cols+x]))continue;const a=point(id),b=point(next);if(!clear(a,b))continue;const cost=scores[id]+(dx&&dy?Math.SQRT2:1);if(cost<scores[next]){scores[next]=cost;parent[next]=id;push(next,cost+heuristic(next));}}
      }
      if(!reached)return null;
      const raw=[end];for(let id=to;id!==from;id=parent[id]){if(id<0)return null;raw.push(point(id));}raw.push(point(from));raw.reverse();
      const smooth=[];let anchor=start,i=0;while(i<raw.length){let j=i;while(j+1<raw.length&&clear(anchor,raw[j+1]))j++;smooth.push(raw[j]);anchor=raw[j];i=j+1;}return smooth;
    }
    return {route,clear};
  }
};
