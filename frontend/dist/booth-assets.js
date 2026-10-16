/* Rooftop booth artwork. Uses the shared projection; leaves map geometry untouched. */
(() => {
  'use strict';
  const themes={
    'festival-youtube':{accent:'#d56558',soft:'#efdbd0',dark:'#43534e',title:'YouTube',subtitle:'CREATOR STUDIO',platform:'youtube'},
    'festival-instagram':{accent:'#9283a7',soft:'#e6dfed',dark:'#5d586c',title:'MIND LAB',subtitle:'PSYCHOLOGY TEST',platform:'psych'},
    'festival-booth3':{accent:'#658c97',soft:'#d6e5e5',dark:'#334a55',title:'GAME ARCADE',subtitle:'PLAY • DISCOVER',platform:'game'},
  };
  const types=new Set(['exhibition-booth','booth-side','creator-screen','camera-tripod','microphone-stand',
    'creator-console','creator-award','psych-test-backdrop','psych-type-wheel','psych-question-kiosk',
    'psych-mood-cards','game-arcade','game-brand-sign','game-pc-station','game-console-display','stool']);

  function paint(o,A,base){
    const theme=themes[o.roomId];
    if(!theme||!types.has(o.type))return false;
    const {g,p,box,plane,line,ellipse,verticalPanel,drawingVector,platformIcon,circlePlane,font}=A;
    const {x,y,w,h}=o;
    const wood=['#cfb68e','#b49a76','#9c8568'],cream=['#faf5e8','#e3dbca','#c8c3b5'];
    const block=(bx,by,bw,bh,z,height,colors=wood)=>box(bx,by,bw,bh,base+z,height,...colors);
    const segment=(ax,ay,az,bx,by,bz,color,width=1)=>line(p(ax,ay,base+az),p(bx,by,base+bz),color,width);
    function face(bx,by,bw,bh,z,draw){
      const v=drawingVector(1,0),q=p(bx,by,base+z+bh);
      g.save();g.transform(v.x,v.y,0,1,q.x,q.y);draw(bw,bh);g.restore();
    }
    function text(value,tx,ty,size,color,limit,weight=600){
      g.font=`${weight} ${size}px ${font}`;g.fillStyle=color;g.textAlign='center';g.textBaseline='middle';g.fillText(value,tx,ty,limit);
    }
    function rounded(bx,by,bw,bh,r,fill,stroke){
      g.beginPath();g.roundRect(bx,by,bw,bh,r);g.fillStyle=fill;g.fill();
      if(stroke){g.strokeStyle=stroke;g.lineWidth=.8;g.stroke();}
    }
    function screen(bx,by,bw,bh,z,kind){
      face(bx,by,bw,bh,z,(width,height)=>{
        rounded(0,0,width,height,2,'#283c42','#869e9b');
        g.fillStyle='#c2d4cf';g.fillRect(3,3,width-6,3);
        if(kind==='edit'){
          g.fillStyle='#172b32';g.fillRect(3,8,width*.65,height*.46);
          platformIcon(width*.34,height*.32,Math.min(17,height*.36),'youtube');
          for(let i=0;i<4;i++){g.fillStyle=['#cfbb94','#96bcb6','#d18478','#809eaa'][i];g.fillRect(width*.73,9+i*5,width*.19,3);}
          g.fillStyle='#172d34';g.fillRect(3,height*.61,width-6,height*.31);
          for(let i=0;i<3;i++){g.fillStyle=['#bc786a','#8cb6a7','#c1ad80'][i];g.fillRect(5+i*5,height*.67+i*5,width*.56-i*5,3);}
          g.fillStyle='#f5edd5';g.fillRect(width*.49,height*.6,1,height*.33);
        }else if(kind==='steam'){
          const cx=width*.5,cy=height*.42,r=Math.min(width,height)*.25;
          ellipse(cx,cy,r,r,'#456779');
          line({x:cx-r*.85,y:cy+r*.4},{x:cx-r*.12,y:cy+r*.72},'#f4f4e5',r*.25);
          line({x:cx-r*.1,y:cy+r*.48},{x:cx+r*.46,y:cy-r*.35},'#f4f4e5',r*.25);
          for(const [dx,dy,size] of [[-.14,.55,.29],[.5,-.4,.39]]){
            g.beginPath();g.arc(cx+dx*r,cy+dy*r,r*size,0,Math.PI*2);g.strokeStyle='#f4f4e5';g.lineWidth=r*.13;g.stroke();
          }
          text('STEAM',width/2,height*.83,7,'#e6ece3',width-7);
        }else{
          g.fillStyle='#183542';g.fillRect(3,8,width-6,height-11);
          g.fillStyle='#566971';g.fillRect(4,height-7,width-8,3);
          const color=kind==='puzzle'?'#d3b997':'#9bc4b6';
          if(kind==='puzzle')for(let i=0;i<4;i++)for(let j=0;j<3;j++){
            g.fillStyle=(i+j)%3===0?color:'#6c94a5';g.fillRect(6+i*(width-13)/4,11+j*5,(width-16)/4,3.4);
          }else{
            g.fillStyle='#e6d6a1';g.fillRect(width*.2,height*.41,4,4);g.fillStyle=color;g.fillRect(width*.55,height*.28,6,6);
            g.fillStyle='#b88279';g.fillRect(width*.7,height*.58,4,5);g.strokeStyle='#739eac';g.lineWidth=1;
            g.beginPath();g.moveTo(7,height*.74);g.lineTo(width*.39,height*.51);g.lineTo(width*.5,height*.63);g.lineTo(width-5,height*.25);g.stroke();
          }
        }
      });
    }

    if(o.type==='exhibition-booth'){
      block(x,y,w,10,0,126,cream);
      block(x,y,w,12,0,6,['#bca78a','#9d896f','#8e7e68']);
      face(x+9,y+10,w-18,109,8,(width,height)=>{
        g.fillStyle='#f0e8d8';g.fillRect(0,0,width,height);
        for(let i=0;i<width;i+=13){g.fillStyle=i%26?'#d9c9ad':'#dfcfb5';g.fillRect(i,height*.45,6,height*.55);}
        rounded(17,18,width-34,height*.41,3,theme.soft);
        platformIcon(width*.19,height*.32,24,theme.platform);
        text(theme.subtitle,width*.62,height*.32,11,theme.dark,width*.63);
        g.strokeStyle='#c5b69b';g.lineWidth=.8;g.beginPath();g.moveTo(0,height-1);g.lineTo(width,height-1);g.stroke();
      });
      for(const bx of [x,x+w-8])block(bx,y,8,12,0,145,wood);
      block(x-1,y-1,w+2,14,126,20,['#eee3ce','#d5c3a3','#b7a58c']);
      face(x+11,y+13,w-22,17,128,(width,height)=>{
        g.fillStyle=theme.dark;g.fillRect(0,0,width,height);platformIcon(16,height/2,11,theme.platform);
        text(theme.title,width/2+8,height/2,15,'#fff9e9',width-48,700);
      });
      for(const bx of [x+45,x+w-49]){
        segment(bx,y+7,146,bx,y+18,150,'#6b7264',1.4);
        const q=p(bx,y+18,base+149);ellipse(q.x,q.y,3,1.7,'#f8e6aa');
      }
    }else if(o.type==='booth-side'){
      // Same body and cap colours as the campus walls, so the long face reads as a wall rather than a grey sheet.
      // The panel butts onto the backdrop's corner post (8 wide, 12 deep) and shares its outer face,
      // so it continues the post instead of stepping out beside it.
      const outer=x<140?x:x+w-8,py=y+12,ph=h-12;
      block(outer,py,8,ph,0,31,['#eee5d0','#c8b99a','#b4a387']);
      block(outer,py,8,ph,31,5,['#8d775b','#917656','#786449']);
      // A thin accent strip makes the shared timber frame belong to its zone; the post is painted over its end.
      plane(outer+.5,py+.5,7,ph-13.5,base+36.3,theme.soft,null);
      // Only the open front end has a post, a unit proud of the panel on both faces so it reads as a post.
      block(x-1,y+h-11,w+2,10,0,58,wood);block(x-2,y+h-12,w+4,12,58,3,cream);
    }else if(o.type==='creator-screen'){
      for(const bx of [x+17,x+w-23])block(bx,y+5,6,8,0,39,['#78877e','#586a64','#3f5350']);
      verticalPanel(x,y+h,w,66,base+35,'#374b4f');screen(x+5,y+h,w-10,55,42,'edit');
      face(x+2,y+h,w-4,6,35,(width,height)=>{g.fillStyle='#e7d7b6';g.fillRect(0,0,width,height);text('LIVE • EDIT',width/2,height/2,5,'#68726b',width-8);});
    }else if(o.type==='camera-tripod'){
      const cx=x+w/2,cy=y+h/2;
      for(const [dx,dy] of [[-w*.35,h*.32],[w*.35,h*.3],[0,-h*.27]])segment(cx,cy,63,cx+dx,cy+dy,2,'#4b5d58',2.3);
      block(cx-2,cy-2,4,4,45,20,['#a5b0a4','#778b82','#536b63']);
      block(cx-13,cy-9,27,18,65,18,['#5f6f65','#374a46','#283b38']);
      face(cx+3,cy+10,20,20,65,(width,height)=>{
        rounded(0,0,width,height,4,'#253b3b');ellipse(width/2,height/2,7.4,7.4,'#719c9a');ellipse(width/2,height/2,5,5,'#1d3e49');ellipse(width/2-2,height/2-2,2,2,'#d3eadc');
      });
      const led=p(cx-9,cy+10,base+78);ellipse(led.x,led.y,1.5,1.5,'#e9a090');
    }else if(o.type==='microphone-stand'){
      const cx=x+w/2,cy=y+h/2,q=p(cx,cy,base+1);
      ellipse(q.x,q.y,12,4,'#566960');segment(cx,cy,2,cx,cy,72,'#788a7c',2.5);
      segment(cx,cy,72,cx+11,cy,87,'#4d625b',2.5);
      const mic=p(cx+12,cy,base+88);rounded(mic.x-4,mic.y-10,8,19,3,'#344a47','#94a094');
      g.strokeStyle='#b2bcae';g.lineWidth=.6;for(let i=0;i<4;i++){g.beginPath();g.moveTo(mic.x-2,mic.y-7+i*3);g.lineTo(mic.x+2,mic.y-7+i*3);g.stroke();}
      const filter=p(cx+17,cy+4,base+86);g.beginPath();g.arc(filter.x,filter.y,7,0,Math.PI*2);g.fillStyle='#53645caa';g.fill();g.strokeStyle='#2f4942';g.lineWidth=1.4;g.stroke();
      g.beginPath();g.moveTo(mic.x,mic.y+8);g.bezierCurveTo(mic.x+12,mic.y+35,q.x-8,q.y-24,q.x+3,q.y);g.strokeStyle='#70816f';g.lineWidth=.9;g.stroke();
    }else if(o.type==='creator-console'){
      for(const [dx,dy] of [[5,5],[w-10,5],[5,h-9],[w-10,h-9]])block(x+dx,y+dy,4,4,0,31,wood);
      block(x,y,w,h,31,5,cream);block(x+2,y+h-5,w-4,4,8,22,wood);
      block(x+w*.32,y+11,11,8,36,7,['#89998b','#647c70','#4c665e']);
      screen(x+8,y+16,w*.62,39,43,'edit');
      plane(x+17,y+h-19,w*.47,10,base+36.3,'#687a72','#95a396');
      for(let i=0;i<10;i++)segment(x+20+i*4,y+h-17,36.7,x+20+i*4,y+h-11,36.7,'#b7c4b1',.45);
      block(x+w-25,y+14,18,27,36,30,['#6b7f70','#455f52','#344a43']);
      face(x+w-24,y+41,16,25,38,(width,height)=>{g.fillStyle='#344e46';g.fillRect(0,0,width,height);for(let i=0;i<4;i++){g.fillStyle='#98af96';g.fillRect(3,4+i*4,width-6,1);}ellipse(width/2,height-5,1.2,1.2,'#b9d7ad');});
    }else if(o.type==='creator-award'){
      block(x+2,y+2,w-4,h-4,0,22,wood);
      face(x+6,y+h,w-12,58,24,(width,height)=>{
        rounded(0,0,width,height,3,'#d1c2a0','#a69a7d');rounded(3,3,width-6,height-6,2,'#ece6d3');
        platformIcon(width/2,height*.4,17,'youtube');text('CREATOR',width/2,height*.74,4.5,'#758278',width-6);
      });
    }else if(o.type==='psych-test-backdrop'){
      block(x+3,y+2,w-6,h-3,0,24,wood);
      face(x+8,y+h-2,w-16,105,27,(width,height)=>{
        rounded(0,0,width,height,6,'#f6f1e9','#bcafc4');
        rounded(8,8,width-16,24,5,theme.soft);platformIcon(width/2,20,16,'psych');
        const colors=['#e2c3b9','#e0d2a3','#bfd4c4','#c4c2df'];
        for(let i=0;i<4;i++){
          const bx=9+i*(width-18)/4,card=(width-23)/4;
          rounded(bx,43,card,35,4,colors[i]);
          ellipse(bx+card*.4,54,1.1,1.2,'#77676e');ellipse(bx+card*.6,54,1.1,1.2,'#77676e');
          g.beginPath();g.arc(bx+card*.5,58,3,0,Math.PI);g.strokeStyle='#86777c';g.lineWidth=.8;g.stroke();
          text(['E','N','F','P'][i],bx+card/2,70,7,'#6c6770',card-4);
        }
        text('마음 유형 연구소',width/2,92,10,theme.dark,width-12);
      });
    }else if(o.type==='psych-type-wheel'){
      block(x+5,y+9,w-10,h-14,0,20,wood);
      face(x+3,y+h-3,w-6,76,22,(width,height)=>{
        rounded(0,0,width,height,5,'#f7f1e7','#bcb2c3');
        const cx=width/2,cy=30,r=15,colors=['#ddacaa','#dec995','#b8cead','#aac8ca','#beb4d3','#d4b2c3'];
        for(let i=0;i<6;i++){
          g.beginPath();g.moveTo(cx,cy);g.arc(cx,cy,r,i*Math.PI/3,(i+1)*Math.PI/3);g.closePath();g.fillStyle=colors[i];g.fill();
        }
        ellipse(cx,cy,5,5,'#f8f3e7');g.fillStyle='#70627c';g.beginPath();g.moveTo(cx,cy-r-6);g.lineTo(cx-3,cy-r-1);g.lineTo(cx+3,cy-r-1);g.fill();
        text('MIND',cx,56,6.5,theme.dark,width-8);text('나를 알아보기',cx,66,4.8,'#8b7d8c',width-8);
      });
    }else if(o.type==='psych-question-kiosk'){
      block(x+7,y+7,w-14,h-14,0,6,wood);block(x+12,y+10,w-24,h-20,6,47,cream);
      block(x+4,y+7,w-8,11,53,66,['#d4c8df','#a699b4','#83778f']);
      face(x+6,y+19,w-12,58,57,(width,height)=>{
        rounded(0,0,width,height,4,'#40584f');rounded(3,3,width-6,height-6,2,'#f1eee5');
        rounded(6,7,width-12,12,3,theme.soft);text('?',width/2,13,10,theme.dark,width-8);
        for(let i=0;i<3;i++)rounded(6,25+i*8,width-12,5,2,['#dfd6e9','#e2d2c0','#cbdac9'][i]);
      });
    }else if(o.type==='psych-mood-cards'){
      block(x,y,w,h,0,20,wood);block(x,y,w,h,20,4,cream);
      for(let i=0;i<4;i++){
        face(x+7+i*(w-13)/4,y+h-3,(w-20)/4,32,25,(width,height)=>{
          rounded(0,0,width,height,3,['#dfbdad','#deca96','#bdd0b6','#bdb5ce'][i],'#b4ab9b');
          ellipse(width*.38,height*.35,1.1,1.1,'#766b69');ellipse(width*.62,height*.35,1.1,1.1,'#766b69');
          g.beginPath();g.arc(width/2,height*.42,3.2,0,Math.PI);g.strokeStyle='#8b7870';g.lineWidth=.8;g.stroke();
          text(['설렘','평온','집중','휴식'][i],width/2,height*.79,5,'#746a68',width-3);
        });
      }
    }else if(o.type==='game-arcade'){
      const accent=o.color==='#8467b5'?'#9b86a5':'#688d9c';
      block(x,y,w,h,0,53,['#7a9291','#415e64','#2e454e']);
      block(x+2,y+4,w-4,h*.42,53,52,['#55737b','#344c58','#253b47']);
      screen(x+8,y+h*.42,w-16,36,62,o.color==='#8467b5'?'puzzle':'arcade');
      block(x-1,y+h*.43,w+2,h*.36,53,6,['#cfb98f','#a39175','#877c67']);
      const joy=p(x+w*.28,y+h*.63,base+66);ellipse(joy.x,joy.y,4,2,'#344c51');line(joy,{x:joy.x,y:joy.y-8},'#8c9b94',1.7);ellipse(joy.x,joy.y-9,2.8,2.8,accent);
      for(const [dx,dy,color] of [[.64,.56,'#b3caad'],[.77,.62,'#d8b291'],[.62,.7,'#aca5c9']]){const q=p(x+w*dx,y+h*dy,base+59.6);ellipse(q.x,q.y,2.8,2,color);}
      face(x+3,y+h*.42,w-6,13,103,(width,height)=>{g.fillStyle=accent;g.fillRect(0,0,width,height);text(o.color==='#8467b5'?'PUZZLE':'ARCADE',width/2,height/2,7,'#fff5dd',width-6,700);});
      face(x+5,y+h,w-10,35,7,(width,height)=>{g.fillStyle='#3a555a';g.fillRect(0,0,width,height);for(let i=0;i<3;i++){g.fillStyle=accent;g.fillRect(4+i*4,3,2,height-6);}rounded(width-13,13,8,14,1,'#253a41');g.fillStyle='#93a297';g.fillRect(width-11,17,4,1);});
    }else if(o.type==='game-brand-sign'){
      face(x+6,y+h,w-12,16,97,(width,height)=>{
        rounded(0,0,width,height,2,'#e4d9c1');
        text('Nintendo',width*.25,height/2,9,'#b56b61',width*.45);
        g.fillStyle='#b8b3a4';g.fillRect(width/2,height*.23,.6,height*.54);
        text('STEAM',width*.75,height/2,9,'#577480',width*.45);
      });
    }else if(o.type==='game-pc-station'){
      for(const [dx,dy] of [[4,4],[w-8,4],[4,h-8],[w-8,h-8]])block(x+dx,y+dy,4,4,0,33,wood);
      block(x,y,w,h,33,5,['#c2b08d','#9d8c71','#847c67']);
      block(x+22,y+9,13,9,38,7,['#8a9e97','#607b76','#40595c']);
      screen(x+6,y+18,w-31,37,44,'steam');
      block(x+w-22,y+7,17,28,38,41,['#657a7d','#324a53','#243c47']);
      face(x+w-20,y+35,13,35,40,(width,height)=>{
        g.fillStyle='#263f4a';g.fillRect(0,0,width,height);
        for(let i=0;i<3;i++){ellipse(width/2,7+i*10,3.4,3.4,['#90b9ab','#9daece','#baa4c6'][i]);ellipse(width/2,7+i*10,1.7,1.7,'#304e56');}
      });
      plane(x+8,y+h-23,40,12,base+38.3,'#465d5a','#8fa28c');
      for(let i=0;i<9;i++)segment(x+11+i*4,y+h-21,38.6,x+11+i*4,y+h-14,38.6,'#c2c6ac',.5);
      block(x+w-19,y+h-19,9,11,38,2,['#99aca3','#748d83','#566e69']);
    }else if(o.type==='game-console-display'){
      block(x,y,w,h,0,33,wood);block(x,y,w,h,33,4,cream);
      block(x+w-24,y+5,18,10,37,16,['#4b6467','#344d52','#273d44']);
      face(x+6,y+21,w-12,27,42,(width,height)=>{
        rounded(0,0,width,height,4,'#263e48');rounded(0,0,8,height,3,'#64b3bf');rounded(width-8,0,8,height,3,'#d7877a');
        g.fillStyle='#c5d9c5';g.fillRect(10,4,width-20,height-8);g.fillStyle='#8eb9ac';g.fillRect(10,height-10,width-20,6);ellipse(width*.53,10,2.5,2.5,'#f0dfae');
        ellipse(4,8,1.8,1.8,'#31515c');ellipse(width-4,height-8,1.8,1.8,'#704e48');
        for(const [bx,by] of [[3,19],[5,19],[4,17],[4,21],[width-5,8],[width-3,8],[width-4,6],[width-4,10]])ellipse(bx,by,.55,.55,'#314b51');
      });
      face(x+4,y+h,w-8,11,13,(width,height)=>{g.fillStyle='#ead7bd';g.fillRect(0,0,width,height);text('Nintendo',width/2,height/2,7,'#9f6b5a',width-6);});
    }else if(o.type==='stool'){
      const cx=x+w/2,cy=y+h/2;
      circlePlane(cx,cy,w*.35,base+.3,'#8e9b8755',null);
      for(const [dx,dy] of [[-5,-5],[5,-5],[0,6]])block(cx+dx-1,cy+dy-1,2,2,1,18,wood);
      block(x+3,y+3,w-6,h-6,18,5,[theme.soft,theme.accent,'#8b968c']);
      plane(x+5,y+5,w-10,h-10,base+23.2,theme.soft,null);
    }
    return true;
  }

  function paintFloor(data,A){
    for(const rug of data.objects.filter(o=>o.type==='rug'&&themes[o.roomId])){
      const {x,y,w,h}=rug,z=A.groundHeight(x,y);
      A.plane(x+1,y+1,w-2,h-2,z+.1,'#d6c19f',null);
      for(let by=y+3,index=0;by<y+h-3;by+=19,index++){
        A.plane(x+3,by,w-6,Math.min(17,y+h-3-by),z+.2,index%2?'#e0ceb0':'#e5d5b9',null);
        A.line(A.p(x+3,by,z+.25),A.p(x+w-3,by,z+.25),'#bdaa8b70',.5);
      }
      A.plane(x+w-7,y+3,4,h-6,z+.25,themes[rug.roomId].soft,null);
    }
  }
  window.CampusBoothAssets={paint,paintFloor};
})();
