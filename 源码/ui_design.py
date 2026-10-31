"""Modern navigation shell, task tiles, and interruptible page transitions."""
import sys
import time
from ui_render import Surface, Compositor, gdi


class VisualShell:
    def api(self):
        return sys.modules[type(self).__module__]

    @property
    def prompt(self):
        return getattr(self, '_prompt', None)

    @prompt.setter
    def prompt(self, value):
        previous = getattr(self, '_prompt', None)
        self._prompt = value
        if bool(previous) == bool(value) or not getattr(self, 'hwnd', None):
            return
        self.finish_modal_transition()
        a = self.api()
        self._hover_patch = None
        scene = getattr(self, '_last_scene', None)
        # 材质模式下弹窗是不透明呈现的，做淡入淡出既没必要也看不出效果
        if (scene and self.motion_enabled() and self._compositor.alpha
                and self.frame_effect not in ('mica', 'tabbed', 'acrylic')
                and a.user32.IsWindowVisible(self.hwnd) and not a.user32.IsIconic(self.hwnd)):
            self.finish_transition()
            self._modal_transition = (scene.clone(), time.monotonic(), bool(value),
                                      self.rects.get('prompt'))
            self._animation_clock.start()
            a.user32.SetTimer(self.hwnd, 4, 16, None)
        a.user32.InvalidateRect(self.hwnd, None, False)

    def finish_modal_transition(self):
        transition = getattr(self, '_modal_transition', None)
        if transition:
            transition[0].close()
        self._modal_transition = None
        if hasattr(self,'_compositor'):
            self._compositor.finish_animation()
        self._visual_generation = getattr(self, '_visual_generation', 0)+1
        if not getattr(self, '_transition', None) and hasattr(self, '_animation_clock'):
            self._animation_clock.stop()
        if getattr(self, 'hwnd', None):
            self.api().user32.KillTimer(self.hwnd, 4)

    @property
    def page(self):
        return getattr(self, '_page', 'main')

    @page.setter
    def page(self, value):
        old = getattr(self, '_page', None)
        self._page = value
        if old == value or not getattr(self, 'hwnd', None):
            return
        self.finish_transition()
        scene = getattr(self, '_last_scene', None)
        compositor = getattr(self, '_compositor', None)
        if scene and compositor and compositor.alpha and self.motion_enabled():
            depths = {'main': 0, 'settings': 1, 'custom': 2, 'night': 2, 'tasks': 2, 'about': 2}
            self._transition = (scene.clone(), time.monotonic(),
                                1 if depths.get(value, 1) >= depths.get(old, 1) else -1)
            self._animation_clock.start()
            self.api().user32.SetTimer(self.hwnd, 3, 16, None)
        self.hover = self.pressed = None
        # 换页必须整帧重算：patch 是「在上一帧上打补丁」，底图还是旧页面就全错了
        self._hover_patch = None
        self.api().user32.InvalidateRect(self.hwnd, None, False)

    def finish_transition(self):
        current = getattr(self, '_transition', None)
        if current:
            current[0].close()
        self._transition = None
        if hasattr(self,'_compositor'):
            self._compositor.finish_animation()
        self._visual_generation = getattr(self, '_visual_generation', 0)+1
        if not getattr(self, '_modal_transition', None) and hasattr(self, '_animation_clock'):
            self._animation_clock.stop()
        if getattr(self, 'hwnd', None):
            self.api().user32.KillTimer(self.hwnd, 3)

    def present_scene(self, target, scene, w, h, patch=None, text_rects=None):
        a = self.api()
        output = scene
        animation_progress=None
        animation_offset=0
        animation_kind='page'
        # 模态弹窗（询问卡 / 选 exe）在材质模式下按不透明呈现：
        # 遮罩本身就是一层实色，透出去只会让卡片和文字一起发灰，
        # 还会把桌面的内容混进来。页面的 Mica 只在这个弹窗关掉后才恢复。
        material_on = self.frame_effect in ('mica', 'tabbed', 'acrylic')
        material_on = material_on and not (self.prompt or self.exepick)
        native_animation=material_on and self._compositor.last_argb is not None
        endpoint_modal=1.0 if self.prompt or self.exepick else 0.0
        if (self._transition or self._modal_transition) and (
                self._animation_scene is None or self._animation_generation != self._visual_generation):
            if self._animation_scene:
                self._animation_scene.close()
            self._animation_scene = Surface(target, w, h)
            self._animation_scene.copy(scene)
            self._animation_generation = self._visual_generation
        transition = getattr(self, '_transition', None)
        temp = None
        if transition:
            previous, started, direction = transition
            t = min(1.0, (time.monotonic()-started)/0.28)
            if not self.motion_enabled() or t >= 1 or (previous.width, previous.height) != (w, h):
                self.finish_transition()
            else:
                eased = 1-(1-t)**3
                animation_progress=t
                animation_offset=self.S(22*(1-eased)*direction)
                if not native_animation:
                    temp = self.blend_surface(target, w, h)
                    temp.copy(previous.dc)
                    split = self.S(196)
                    self._compositor.blend(temp.dc, scene, (split, 0, w, h),
                                           round(255*eased), self.S(22*(1-eased)*direction))
                    self._compositor.blend(temp.dc, scene, (0, 0, split, h), 255)
                    output = temp.dc
        modal_amount = 1.0 if self.prompt or self.exepick else 0.0
        dialog = self.rects.get('prompt' if self.prompt else 'expick')
        modal = getattr(self, '_modal_transition', None)
        if modal:
            previous, started, opening, old_dialog = modal
            t = min(1.0, (time.monotonic()-started)/0.22)
            if not self.motion_enabled() or t >= 1 or (previous.width, previous.height) != (w, h):
                self.finish_modal_transition()
            else:
                eased = 1-(1-t)**3
                animation_progress=eased
                animation_offset=0
                animation_kind='modal'
                endpoint_modal=1.0 if opening else 0.0
                modal_amount = eased if opening else 1-eased
                dialog = dialog if opening else old_dialog
                if not native_animation:
                    temp = self.blend_surface(target, w, h)
                    temp.copy(previous.dc if opening else scene)
                    self._compositor.blend(temp.dc, scene if opening else previous.dc,
                                           (0, 0, w, h), round(255*(eased if opening else 1-eased)))
                    output = temp.dc
        cached = getattr(self, '_last_scene', None)
        if cached and (cached.width, cached.height) != (w, h):
            cached.close()
            cached = None
        if cached is None:
            cached = self._last_scene = Surface(target, w, h)
        if patch is not None:
            # 局部刷新：只把那几块抄进「上一帧」，其余像素本来就没变。
            # _last_scene 必须始终等于屏幕上这一帧的场景，否则下一次差分
            # 会以为没变化，把补丁打到对不上的底图上。
            for rect in patch:
                cached.copy_rect(output, rect)
        else:
            cached.copy(output)
        regions = [((0, 0, self.S(192), h), 218),
                   ((self.S(204), self.S(12), w-self.S(20), self.S(86)), 226)]
        if self.page == 'main':
            regions.append((self.rects['hero'], 212))
            regions.append(((self.S(212), self.S(184), w-self.S(28), self.S(211)), 232))
            regions.extend((r, 218) for r in self.rects.get('tiles', {}).values())
        else:
            regions.append((self.rects['card'], 222))
        regions.append((self.rects['logcard'], 208))
        for key in ('start', 'cancel', 'shutdown', 'night') if self.page == 'main' else ('edit',):
            regions.append((self.rects[key], 246))
        regions.append((self.rects['statusbar'], 218))
        endpoint_regions=list(regions)
        if endpoint_modal:
            endpoint_regions=[((0,0,w,h),110)] + ([(dialog,240)] if dialog else [])
        if modal_amount > 0:
            regions = [(r, round(opacity*(1-modal_amount))) for r, opacity in regions]
            regions.append(((0, 0, w, h), round(110*modal_amount)))
            if dialog:
                regions.append((dialog, round(240*modal_amount)))
        animation=(self._visual_generation,animation_progress,animation_offset,endpoint_regions,animation_kind,self.S(196)) if animation_progress is not None else None
        self._compositor.text_layers = getattr(self, "_glass_text_layers", None)
        self._compositor.material = self.frame_effect
        ok = self._compositor.present(target, self._animation_scene.dc if animation and native_animation else output,
                                      w, h, regions, material_on,
                                      animation if material_on else None,
                                      patch=patch if (material_on and not animation) else None,
                                      text_rects=text_rects if material_on and not animation else None)
        if not ok:
            self.frame_effect = a.apply_native_frame(self.hwnd, False)
            # 材质提交失败时退回不透明；这时同样要先把文字层合回场景
            self._compositor.present(target, output, w, h, regions, False, None)

    def blend_surface(self, target, w, h):
        surface = getattr(self, '_blend_surface', None)
        if surface and (surface.width, surface.height) != (w, h):
            surface.close()
            surface = None
        if surface is None:
            surface = self._blend_surface = Surface(target, w, h)
        return surface

    def material_name(self):
        """标签显示**实际生效**的材质，而不是配置里写的愿望。

        默认想要 Mica；系统不支持（Win10 / 旧版 11 / 关掉透明效果 / 取不到合成器）时
        会静默回退实色 —— 这种情况下再显示「Mica」就是在骗人。
        """
        want=self.cfg.get('ui_material','mica') if self.cfg.get('ui_mica',True) else 'solid'
        actual=getattr(self,'frame_effect','solid')
        if actual=='unsupported':
            return '实色（本机不支持 Mica）'
        if actual=='unavailable':
            return '实色（Mica 调用失败）'
        material=actual if actual in ('mica','tabbed','acrylic','solid') else want
        return {'mica':'Mica','tabbed':'Tabbed / Mica Alt','acrylic':'亚克力','solid':'实色'}.get(material,'Mica')

    def setting_button(self,item):
        """Separate the observed state from the exact action on activation."""
        key=item['key'];chip=item.get('chip','');cfg=self.cfg
        if key in ('t_hint','n_hint'):
            return '功能说明','',False
        if key in ('ui_motion','ui_mica') or key.startswith('t_flag:'):
            if key.startswith('t_flag:'):
                section,field=key[7:].split('.',1)
                on=bool(cfg.get(section,{}).get(field,True))
            else:
                on=bool(cfg.get(key,True))
            return '当前：'+('开启' if on else '关闭'),'点击'+('关闭' if on else '开启'),True
        if key=='ui_material':
            choices=['mica','tabbed','acrylic','solid']
            current=cfg.get('ui_material','mica') if cfg.get('ui_mica',True) else 'solid'
            if current not in choices:current='mica'
            names={'mica':'Mica','tabbed':'Tabbed','acrylic':'亚克力','solid':'实色'}
            nxt=choices[(choices.index(current)+1)%4]
            return '当前：'+names[current],'切换为 '+names[nxt],True
        if key in ('maa_instance','fgo_instance'):
            indexes=self._inst_indexes()
            current=int(cfg.get('maa' if key=='maa_instance' else 'maafgo',{}).get(
                'instance_index' if key=='maa_instance' else 'emulator_index',0 if key=='maa_instance' else 1))
            nxt=indexes[(indexes.index(current)+1)%len(indexes)] if indexes and current in indexes else indexes[0] if indexes else None
            return '当前：实例%d'%current,('切换到 实例%d'%nxt if nxt is not None and nxt!=current else '仅有此实例' if nxt is not None else '请先选择模拟器'),nxt is not None and nxt!=current
        if key=='fgo_ver':
            packages=self.api().FGO_PACKAGES
            current=cfg.get('maafgo',{}).get('game_package','')
            idx=next((i for i,(_,p) in enumerate(packages) if p==current),-1)
            return '当前：'+str(chip),'切换到 '+packages[(idx+1)%len(packages)][0],True
        if key.startswith('t_mx:'):
            options=self._mxu_options(key[5:])
            current=(cfg.get(key[5:],{}).get('instance') or '').strip()
            nxt=options[(options.index(current)+1)%len(options)] if options and current in options else options[0] if options else ''
            return '当前：'+(current or '未设置'),('切换为 '+nxt if len(options)>1 else '仅有此配置' if options else '先初始化脚本'),len(options)>1
        if key=='t_okww':
            current=cfg.get('okww',{}).get('task','')
            return '当前：'+str(chip),'改为 '+('只打开程序' if current=='DailyTask' else '每日任务'),True
        if key.startswith('n_toggle:'):
            on=key[9:] in set(self.night_items())
            return '当前：'+('已加入夜间' if on else '未加入夜间'),'点击'+('移出清单' if on else '加入清单'),True
        if key=='update':
            state=self.upd.get('state','idle')
            action={'checking':'正在检查…','downloading':'正在下载…','available':'下载新版本','ready':'安装并重启','error':'重新检查'}.get(state,'检查更新')
            return '当前：'+{'idle':'未检查','checking':'检查中','uptodate':'已是最新','available':'发现新版','downloading':'下载中','ready':'已下载','error':'检查失败'}.get(state,str(chip)),action,state not in ('checking','downloading')
        if key=='c_add':
            n=len(cfg.get('custom_items',[]))
            return '当前：%d/%d 个项目'%(n,self.api().MAX_CUSTOM),'点击添加项目',n<self.api().MAX_CUSTOM
        if key.startswith('c_del:'):
            hidden=chip=='恢复'
            return '当前：'+('已隐藏' if hidden else '已显示'),'点击'+('恢复显示' if hidden else '删除自定义项' if key[6:].startswith('custom:') else '隐藏此项目'),True
        if key in ('t_reset','c_restore','n_restore'):
            if key=='t_reset':
                default=all(cfg.get(k.split('.')[0],{}).get(k.split('.')[1])==v for k,v in self.TASK_DEFAULTS.items())
            elif key=='c_restore':
                default=not cfg.get('custom_items') and not cfg.get('hidden_items')
            else:
                default=set(self.night_items())=={'maa','maafgo'}
            return '当前：'+('默认方案' if default else '已自定义'),'点击恢复默认',True
        if key in ('mumu','maaend','maa','maafgo','okww'):
            path=cfg.get('mumu_root','') if key=='mumu' else cfg.get(key,{}).get('path','')
            return '当前：'+('已设置' if path else '未设置'),'点击'+('更换目录' if path else '选择目录'),True
        if key=='config':
            return '当前：本地配置','打开配置文件',True
        return '当前：'+str(chip or '可设置'),'点击设置',True

    NAV = [('main', 'ui_dashboard', '日常控制台'), ('settings', 'ui_sliders', '设置'),
           ('tasks', 'ui_tasks', '安排自动任务'), ('night', 'ui_moon', '夜间清单'),
           ('custom', 'ui_apps', '项目管理'), ('about', 'ui_info', '关于')]

    def nav_rects(self):
        return [(page, (self.S(16), self.S(106+i*48), self.S(178), self.S(148+i*48)))
                for i, (page, _, _) in enumerate(self.NAV)]

    def draw_shell(self, dc, w, h):
        a, S, C = self.api(), self.S, self.api().C
        self.fill_round(dc, (S(10), S(10), S(184), h-S(10)), 16, a.rgb('#F5F6FC'))
        a.draw_icon(dc, 'launcher', S(26), S(25), S(32))
        self.text(dc, '日常启动器', (S(66), S(23), S(176), S(47)), C['text'], self.font(14, True))
        self.text(dc, 'DAILY LAUNCHER', (S(26), S(66), S(176), S(84)), C['muted'], self.font(9))
        for (page, icon, title), (_, rect) in zip(self.NAV, self.nav_rects()):
            active = self.page == page
            if active or self.hover == 'nav:'+page:
                self.fill_round(dc, rect, 9, C['accent_l'] if active else C['ghost_bg_h'])
            if active:
                self.fill_round(dc, (rect[0]+S(2), rect[1]+S(12), rect[0]+S(5), rect[3]-S(12)),
                                1.5, C['accent'])
            a.draw_icon(dc, icon, rect[0]+S(14), rect[1]+S(10), S(22))
            self.text(dc, title, (rect[0]+S(47), rect[1], rect[2]-S(8), rect[3]),
                      C['accent'] if active else C['text2'], self.font(12, active))
        self.hline(dc, S(26), S(166), h-S(90), C['border'])
        self.dot(dc, S(32), h-S(62), 3, C['ok'])
        self.text(dc, '本地任务工作台', (S(43), h-S(76), S(174), h-S(49)), C['text2'], self.font(10))
        self.text(dc, a.APP_VERSION, (S(26), h-S(48), S(174), h-S(27)), C['muted'], self.font(10))
        title = dict((p, title) for p, _, title in self.NAV).get(self.page, '日常控制台')
        subtitle = {'main': '选好任务，把重复的日常交给自动化。',
                    'settings': '管理程序路径、模拟器连接与界面偏好。',
                    'tasks': '为每个项目安排合适的自动任务。', 'night': '只运行今晚需要处理的手游日常。',
                    'custom': '整理常用项目，让控制台保持简洁。', 'about': '版本信息、作者与项目主页。'}[self.page]
        self.text(dc, title, self.rects['title'], C['text'], self.font(24, True))
        self.text(dc, subtitle, self.rects['sub'], C['text2'], self.font(11.5))

    def draw_hero(self, dc):
        a, S, C = self.api(), self.S, self.api().C
        l,t,r,b = self.rects['hero']
        self.fill_round(dc, (l,t,r,b), 16, a.rgb('#EBECFF'), a.rgb('#DFE1FA'))
        a.draw_icon(dc, 'ui_sparkle', l+S(20), t+S(22), S(38))
        self.text(dc, '让日常，自动发生。', (l+S(74),t+S(16),r-S(175),t+S(43)),
                  C['text'], self.font(18,True))
        count = sum(self.item_checked(it) for it,_,_ in self.rects['rows'])
        self.text(dc, '已选择 %d 项任务  ·  %s' % (count, '正在执行' if self.busy else '准备就绪'),
                  (l+S(74),t+S(48),r-S(150),t+S(71)), C['text2'], self.font(11))
        # Editorial decoration, with no pill/container or interactive styling.
        x=r-S(166)
        self.hline(dc,x,x+S(28),t+S(24),C['accent'])
        self.text(dc,'DAILY, MADE SIMPLE',(x,t+S(31),r-S(18),t+S(47)),C['muted'],self.font(8))
        self.text(dc,'把时间留给热爱',(x,t+S(48),r-S(18),t+S(69)),C['accent'],self.font(11))

    def item_checked(self, item):
        key = item['key']
        if key.startswith('vm'):
            return self.chk.get(int(item['index']), True)
        if key.startswith('custom:'):
            return self.chk_custom.get(key[7:], True)
        return getattr(self, key+'_on', True)

    def draw_task_tile(self, dc, item, rect, step=0):
        a,S,C = self.api(), self.S, self.api().C
        l,t,r,b=rect
        key=item['key']
        checked=self.item_checked(item)
        hot=self.hover_amount('chk:'+key)
        self.fill_round(dc,(l,t+S(2),r,b+S(2)),13,a.rgb('#E6E9F3'))
        self.fill_round(dc,rect,13,a.mix_color(C['card'],C['accent_l'],hot*.55),
                        a.rgb('#D9DCF6') if checked else C['border'])
        a.draw_icon(dc,item.get('icon'),l+S(16),t+S(16),S(38))
        if step:
            # 序号角标：执行顺序是这套流程最重要的信息，光靠"左上到右下"的网格
            # 读不出来（左右两列很容易被看成两条独立的队列）。压在图标左上角，
            # 不占额外版面；没勾选的那项转灰，但序号保留 —— 用户能看出"第 3 步这次跳过"。
            d = S(17)
            bx, by = l + S(9), t + S(9)
            self.fill_round(dc, (bx, by, bx + d, by + d), 8.5,
                            C['accent'] if checked else a.rgb('#C3CBDC'),
                            a.rgb('#FFFFFF'), 1.6)
            self.text(dc, str(step), (bx, by, bx + d, by + d), a.rgb('#FFFFFF'),
                      self.font(9, True),
                      a.DT_CENTER | a.DT_SINGLELINE | a.DT_VCENTER | a.DT_NOPREFIX)
        title=item['title'].replace('MuMu 实例 ','MuMu ')
        self.text(dc,title,(l+S(66),t+S(14),r-S(38),t+S(39)),
                  C['text'] if checked else C['text2'],self.font(12.5,True))
        self.text(dc,item['sub'],(l+S(66),t+S(41),r-S(16),t+S(61)),C['muted'],self.font(9.5),
                  a.DT_LEFT|a.DT_SINGLELINE|a.DT_VCENTER|a.DT_END_ELLIPSIS|a.DT_NOPREFIX)
        box=(r-S(32),t+S(18),r-S(15),t+S(35))
        self.fill_round(dc,box,5,C['accent'] if checked else C['card'],C['accent'] if checked else C['border'])
        if checked:
            self.check_mark(dc,box[0]+S(4),box[1]+S(9),a.rgb('#FFFFFF'))
        state,detail=self.steps.get(key,('idle',''))
        col={'idle':'muted','run':'run','ok':'ok','err':'err'}[state]
        self.dot(dc,l+S(22),b-S(16),3,C[col])
        label=detail or {'idle':'等待启动' if checked else '本次跳过','run':'进行中','ok':'已完成','err':'需要处理'}[state]
        self.text(dc,label,(l+S(33),b-S(28),r-S(16),b-S(5)),C[col],self.font(9.5))

    def draw_main_actions(self, dc):
        a,C=self.api(),self.api().C
        for key,label,primary in [('start','▶  启动所选任务',True),('night','夜间启动',False),
                                  ('cancel','取消启动',False),('shutdown','关闭模拟器',False)]:
            enabled=(not self.busy if key!='cancel' else self.busy)
            fill=C['accent'] if primary and enabled else (C['accent_l'] if primary else C['card'])
            if self.hover==key and enabled:
                fill=C['accent_d'] if primary else C['accent_l']
            text='正在启动…' if key=='start' and self.busy else label
            self.fill_round(dc,self.rects[key],11,fill,None if primary else C['border'])
            self.text(dc,text,self.rects[key],a.rgb('#FFFFFF') if primary and enabled else
                      (C['text2'] if enabled else C['disabled']),self.font(12,primary),
                      a.DT_CENTER|a.DT_SINGLELINE|a.DT_VCENTER|a.DT_NOPREFIX)
