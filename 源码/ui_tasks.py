"""Task planning presentation; uses existing task actions and configuration."""
class TaskPlanner:
    def layout_task_page(self, W, H):
        S=self.S; R=self.rects
        view=getattr(self,'task_view','scripts')
        l,r=212,W-36; top=142; bottom=max(top+100,H-156)
        width=r-l; gap=12; cw=(width-gap)/2
        model={it['key']:it for it in self.task_rows()}
        blocks=[]; groups=[]; y=0
        def add(key,x,y,w,h,label=None):
            item=dict(model[key]);item['task_label']=label or item['title']
            blocks.append((item,(x,y,x+w,y+h)))
        if view=='scripts':
            groups.append(('note',(l,0,r,44),'先选脚本的启动行为','具体关卡、刷取目标等内容，仍在各脚本内配置。',None))
            y=56
            specs=[('maaend','MaaEnd · 终末地','任务配置与自动开始',[('t_mx:maaend','任务配置'),('t_flag:maaend.autostart','自动开始')]),
                   ('maa','MAA · 明日方舟','只控制打开后是否直接执行',[('t_flag:maa.auto_run','自动运行')]),
                   ('maafgo','MaaFgo · FGO','任务配置与自动开始',[('t_mx:maafgo','任务配置'),('t_flag:maafgo.autostart','自动开始')]),
                   ('okww','ok-ww · 鸣潮','选择每日任务或仅打开程序',[('t_okww','启动任务')])]
            for i,(icon,title,sub,controls) in enumerate(specs):
                x=l+(i%2)*(cw+gap); yy=y+(i//2)*152
                groups.append(('tool',(x,yy,x+cw,yy+140),title,sub,icon))
                for j,(key,label) in enumerate(controls):add(key,x+8,yy+44+j*43,cw-16,42,label)
            y+=304
            add('t_reset',l,y,width,54,'恢复脚本默认')
            y+=56
        else:
            add('pl_enabled',l,0,width,62,'分轮执行')
            groups.append(('note',(l,74,r,124),'给每个项目指定轮次','未分配轮次的项目不会启动；同轮按依赖启动，完成后进入下一轮。',None))
            y=138
            assignments=[it for it in model.values() if it['key'].startswith('pl:')]
            builtin=[it for it in assignments if not it['key'].startswith('pl:custom:')]
            custom=[it for it in assignments if it['key'].startswith('pl:custom:')]
            def assignment_grid(items):
                nonlocal y
                for i,it in enumerate(items):
                    x=l+(i%2)*(cw+gap);yy=y+(i//2)*64
                    add(it['key'],x,yy,cw,56)
                y+=((len(items)+1)//2)*64+8
            assignment_grid(builtin)
            groups.append(('note',(l,y,r,y+48),'自定义项目 · %d 项'%len(custom),
                '仅负责打开程序，不会自动执行未适配脚本内的任务。' if custom else
                '在左侧「项目管理」添加并显示项目后，这里会自动出现。',None));y+=60
            assignment_grid(custom)
            enabled=bool((self.cfg.get('pipeline') or {}).get('enabled'))
            rounds=self.task_preview_rounds() if enabled else None
            groups.append(('note',(l,y,r,y+48),'执行预览 · 按主界面勾选生成',
                '仅列出已勾选且已分配轮次的项目。' if enabled else '当前未开启分轮；开启后才会按下方轮次依次执行。',None));y+=56
            if rounds:
                for i,keys in enumerate(rounds):
                    names=' → '.join(self.runner.item_label(k) for k in keys)
                    number=int((self.cfg.get('pipeline') or {}).get('assign',{}).get(keys[0],i+1))
                    groups.append(('preview',(l,y,r,y+48),'第 %d 轮'%number,names,None));y+=56
            else:
                groups.append(('preview',(l,y,r,y+50),'—','暂无执行轮次；请先开启分轮、分配项目并在主界面勾选。',None));y+=58
        self._scroll_max=max(0,int(y-(bottom-top)))
        self.scroll=max(0,min(self.scroll,self._scroll_max));offset=top-self.scroll
        physical=lambda q:tuple(S(v) for v in q)
        shifted=lambda q:physical((q[0],q[1]+offset,q[2],q[3]+offset))
        R['card']=physical((l,top,r,bottom))
        R['edit']=physical((l,bottom+10,l+140,bottom+56))
        R['logcard']=physical((l,bottom+66,r,H-36))
        R['task_tabs']={name:physical((l+i*164,92,l+i*164+156,126)) for i,name in enumerate(('scripts','rounds'))}
        R['task_groups']=[(kind,shifted(q),title,sub,icon) for kind,q,title,sub,icon in groups]
        R['task_controls']={it['key']:shifted(q) for it,q in blocks}
        R['rows']=[(it,shifted(q)[1],shifted(q)[3]-shifted(q)[1]) for it,q in blocks]
        R['disabled_rows']={it['key'] for it,_ in blocks if not self.setting_button(it)[2]}

    def task_page_hit(self,x,y):
        R=self.rects
        for name,q in R.get('task_tabs',{}).items():
            if q[0]<=x<=q[2] and q[1]<=y<=q[3]:return 'task_view:'+name
        card=R['card']
        if not(card[0]<=x<=card[2] and card[1]<=y<=card[3]):return None
        for key,q in R.get('task_controls',{}).items():
            if key not in R.get('disabled_rows',set()) and q[0]<=x<=q[2] and q[1]<=y<=q[3]:return 'set:'+key
        return None

    def draw_task_page(self,dc):
        a=self.api();S=self.S;C=a.C;R=self.rects
        flags=a.DT_LEFT|a.DT_SINGLELINE|a.DT_VCENTER|a.DT_END_ELLIPSIS|a.DT_NOPREFIX
        def text(s,q,color,size=10,bold=False):self.text(dc,s,q,color,self.font(size,bold),flags)
        view=getattr(self,'task_view','scripts')
        for name,q in R['task_tabs'].items():
            active=view==name;hot=self.hover=='task_view:'+name
            self.fill_round(dc,q,10,C['accent'] if active else C['accent_l'] if hot else C['card'],None if active else C['border'])
            text('01  脚本启动' if name=='scripts' else '02  分轮编排',(q[0]+S(18),q[1],q[2]-S(10),q[3]),a.rgb('#FFFFFF') if active else C['text2'],11,True)
        clip=a.gdi32.SaveDC(dc);card=R['card'];a.gdi32.IntersectClipRect(dc,*card)
        for kind,q,title,sub,icon in R['task_groups']:
            l,t,r,b=q
            if b<card[1] or t>card[3]:continue
            self.fill_round(dc,q,12,C['accent_l'] if kind=='note' else C['card'],C['border'] if kind!='note' else None)
            if kind=='tool':
                a.draw_icon(dc,icon,l+S(14),t+S(11),S(26))
                text(title,(l+S(50),t+S(6),r-S(12),t+S(26)),C['text'],12,True)
                text(sub,(l+S(50),t+S(25),r-S(12),t+S(42)),C['muted'],9)
                self.hline(dc,l+S(14),r-S(14),t+S(44),C['line'])
                if icon in ('maa','okww'):
                    hint='沿用 MAA 内已勾选的任务。' if icon=='maa' else '每日任务由 ok-ww 自身执行。'
                    text(hint,(l+S(20),t+S(97),r-S(16),t+S(123)),C['muted'],9)
            elif kind=='note':
                text(title,(l+S(14),t+S(3),r-S(12),t+S(24)),C['accent'],10.5,True)
                text(sub,(l+S(14),t+S(23),r-S(12),b-S(2)),C['text2'],9)
            else:
                self.fill_round(dc,(l+S(12),t+S(10),l+S(65),b-S(10)),7,C['accent_l'])
                text(title,(l+S(17),t,l+S(65),b),C['accent'],10,True)
                text(sub,(l+S(77),t,r-S(14),b),C['text2'],10)
        for item,_,_ in R['rows']:
            q=R['task_controls'][item['key']];l,t,r,b=q
            if b<card[1] or t>card[3]:continue
            key=item['key'];assignment=key.startswith('pl:');full=key in ('pl_enabled','t_reset')
            hot=self.hover=='set:'+key
            if assignment or full:self.fill_round(dc,q,11,C['accent_l'] if hot else C['card'],C['border'])
            elif hot:self.fill_round(dc,q,8,C['accent_l'])
            bw=S(124 if assignment else 142 if full else 132)
            label_l=l+S(12)
            if assignment:
                a.draw_icon(dc,item.get('icon'),l+S(12),t+S(16),S(24));label_l+=S(34)
            right=r-bw-S(10)
            text(item['task_label'],(label_l,t+S(3),right-S(8),b-S(18) if full else b-S(3)),C['text'],10.5,True)
            if full:
                sub='MaaEnd / MAA / MaaFgo / ok-ww 的启动设置；不改动轮次。' if key=='t_reset' else ('已启用 · 本轮全部完成后，才启动下一轮。' if (self.cfg.get('pipeline') or {}).get('enabled') else '当前关闭 · 按原流程启动所有勾选项。')
                text(sub,(label_l,b-S(23),right-S(8),b-S(4)),C['muted'],9)
            current,action,enabled=self.setting_button(item)
            btn=(right,t+S(5),r-S(10),b-S(5))
            self.fill_round(dc,btn,8,C['accent_l'] if hot else C['ghost_bg'],C['border'])
            text(current,(btn[0]+S(8),btn[1]+S(1),btn[2]-S(7),(btn[1]+btn[3])//2),C['text2'],8.5)
            text(action,(btn[0]+S(8),(btn[1]+btn[3])//2,btn[2]-S(7),btn[3]-S(1)),C['accent'] if enabled else C['muted'],9,True)
        a.gdi32.RestoreDC(dc,clip)
        if self._scroll_max:self.draw_scrollbar(dc,card,card[1]+S(6),card[3]-S(6),self.scroll,self._scroll_max)

    def task_preview_rounds(self):
        # Runner's buckets include unchecked/deleted keys; actual execution filters
        # those later. Match the main-page selection without changing the engine.
        visible={it['key']:it for it in self.pipeline_items()}
        return [selected for keys in self.runner.planned_rounds() or []
                if (selected := [key for key in keys if key in visible and self.item_checked(visible[key])])]

    def pipeline_round_options(self):
        return ['不参与（本次不启动）']+['第 %d 轮'%n for n in range(1,self.PIPELINE_MAX_ROUNDS+1)]

    def round_popup(self, raw, current):
        """Native keyboard/screen-reader accessible popup; cancel returns None."""
        import ctypes as c
        from ctypes import wintypes as w
        u=self.api().user32
        u.CreatePopupMenu.argtypes=[];u.CreatePopupMenu.restype=w.HMENU
        u.AppendMenuW.argtypes=[w.HMENU,w.UINT,c.c_size_t,w.LPCWSTR];u.AppendMenuW.restype=w.BOOL
        u.TrackPopupMenuEx.argtypes=[w.HMENU,w.UINT,c.c_int,c.c_int,w.HWND,c.c_void_p]
        u.TrackPopupMenuEx.restype=w.UINT
        u.DestroyMenu.argtypes=[w.HMENU];u.DestroyMenu.restype=w.BOOL
        u.ClientToScreen.argtypes=[w.HWND,c.POINTER(w.POINT)];u.ClientToScreen.restype=w.BOOL
        menu=u.CreatePopupMenu()
        if not menu:return None
        try:
            for value,label in enumerate(self.pipeline_round_options()):
                if not u.AppendMenuW(menu,8 if value==current else 0,value+1,label):return None
            rect=self.rects.get('task_controls',{}).get('pl:'+raw)
            if not rect:return None
            anchor=w.POINT(rect[2]-self.S(134),min(rect[3],self.rects['card'][3]))
            if not u.ClientToScreen(self.hwnd,c.byref(anchor)):return None
            result=u.TrackPopupMenuEx(menu,0x100|0x80,anchor.x,anchor.y,self.hwnd,None)
            return int(result)-1 if result else None
        finally:
            u.DestroyMenu(menu)

    def choose_pipeline_round(self, raw):
        if raw not in {it['key'] for it in self.pipeline_items()}:return
        pl=self.cfg.get('pipeline') or {}
        try:current=int((pl.get('assign') or {}).get(raw,0))
        except (TypeError,ValueError):current=0
        self.hover=self.pressed=None
        self._hover_patch=None
        choice=self.round_popup(raw,current)
        if choice is not None:self.set_pipeline_round(raw,choice)
        self.api().user32.InvalidateRect(self.hwnd,None,False)

    def set_pipeline_round(self, raw, value):
        if self.busy or type(value) is not int or not 0<=value<=self.PIPELINE_MAX_ROUNDS:return
        if raw not in {it['key'] for it in self.pipeline_items()}:return
        pl=self.cfg.setdefault('pipeline',{});assign=pl.setdefault('assign',{})
        pl['enabled']=True
        if value:
            assign[raw]=value
            order=pl.setdefault('order',[])
            if raw not in order:order.append(raw)
        else:assign.pop(raw,None)
        self.api().save_config(self.cfg)
        self._hover_patch=None
        self.status='%s → %s'%(self.runner.item_label(raw),'第 %d 轮'%value if value else '不参与编排')
        self.ui_log(self.status)
