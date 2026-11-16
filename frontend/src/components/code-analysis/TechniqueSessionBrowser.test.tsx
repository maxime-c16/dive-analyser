import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import TechniqueSessionBrowser from './TechniqueSessionBrowser'
import '../../i18n'
const post=vi.fn()
vi.mock('../../services/api',()=>({api:{post:(...args:any[])=>post(...args)}}))
it('pages older months without losing the selected month',async()=>{
 post.mockImplementation(async(_url:string,body:any)=>({data:{revision:2,items:[],next:null,months:body.months_after?[{month:'2001-01',sessions:1}]:[{month:'2026-11',sessions:1}],months_next:body.months_after?null:'2016-11'}}))
 render(<TechniqueSessionBrowser base="/history" context={{code:'5132D'}} revision={2} onChoose={vi.fn()} onReview={vi.fn()} count={0}/>)
 await screen.findByRole('button',{name:'Earlier months'})
 fireEvent.change(screen.getByRole('combobox',{name:'Month'}),{target:{value:'2026-11'}})
 await waitFor(()=>expect(post.mock.lastCall?.[1]).toEqual(expect.objectContaining({month:'2026-11'})))
 await waitFor(()=>expect(screen.getByRole('button',{name:'Earlier months'})).toBeEnabled())
 fireEvent.click(screen.getByRole('button',{name:'Earlier months'}))
 await screen.findByRole('option',{name:'January 2001'})
 expect(screen.getByRole('combobox',{name:'Month'})).toHaveValue('2026-11')
 expect(screen.getByRole('option',{name:'November 2026'})).toBeInTheDocument()
 fireEvent.change(screen.getByRole('combobox',{name:'Month'}),{target:{value:'2001-01'}})
 await waitFor(()=>expect(post.mock.lastCall?.[1]).toEqual(expect.objectContaining({month:'2001-01',months_after:'2016-11'})))
})
