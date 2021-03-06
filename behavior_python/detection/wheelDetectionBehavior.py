from .wheelDetectionSession import *
from behavior_python.core.behavior import Behavior,BehaviorData,BehaviorStats


class WheelDetectionBehaviorData(BehaviorData):
    def __init__(self,dateinterval:str=None) -> None:
        super().__init__(dateinterval)
        self._convert = ['wheel','lick','reward']
        
    def __repr__(self):
        rep = f''' Wheel Detection Behavior Data
        date interval = {self.dateinterval} '''
        return rep
    
    def save(self,path:str)->None:
        """ Saves the data in the given location"""
        super().save(path,'detect')


class WheelDetectionBehavior(Behavior):
    def __init__(self, animalid:str, dateinterval:str=None,*args,**kwargs):
        super().__init__(animalid,dateinterval,*args,**kwargs)
        self.behavior_data = WheelDetectionBehaviorData(dateinterval)
        # get only detection
        self.session_list = self.filter_sessions()
        self.get_behavior(kwargs.get('just_load',False))
        # here is where task specific things could go
        self.behavior_data.filter_dates()
        self.save_behavior()
        
    def filter_sessions(self):
        return [i for i in self.session_list if 'detect' in i[0]]

    @timeit('Getting behavior data...')
    def get_behavior(self,just_load:bool=False):
        """ Loads the behavior data(cumul and summary)"""
        missing_sessions = self.get_unanalyzed_sessions('detect')
        pbar = tqdm(missing_sessions)
        
        if len(missing_sessions) == len(self.session_list):
            # no behavior csv, start from scratch
            cumul_data = pd.DataFrame()
            summary_data = pd.DataFrame()
            session_counter = 0
        else:
            # this loads the most recent found data
            cumul_data = pd.read_pickle(pjoin(self.analysisfolder,self.cumul_file_loc,'detectTrainingData.behave'))
            summary_data = pd.read_csv(pjoin(self.analysisfolder,self.summary_file_loc,'detectTrainingDataSummary.csv'),dtype={'date':str})
            session_counter = summary_data['session_no'].iloc[-1]
            
        if not just_load:
            summary_to_append = []
            for i,sesh in enumerate(pbar):
                pbar.set_description(f'Analyzing {sesh[0]} [{i+1}/{len(missing_sessions)}]')
                detect_session = WheelDetectionSession(sesh[0],load_flag=self.load_data)
                session_data = detect_session.data.data
                
                gsheet_dict = self.get_googlesheet_data(detect_session.meta.baredate,
                                                        cols=['paradigm','supp water [??l]','user','time [hh:mm]','rig water [??l]'])
                
                if len(session_data):
                    # add behavior related fields as a dictiionary
                    summary_temp = {}
                    summary_temp['date'] = detect_session.meta.baredate
                    summary_temp['blank_time'] = detect_session.meta.openStimDuration
                    summary_temp['response_window'] = detect_session.meta.closedStimDuration
                    try:
                        summary_temp['level'] = int(detect_session.meta.level)
                    except:
                        summary_temp['level'] = -1
                    summary_temp['session_no'] = session_counter + 1
                    summary_temp['weight'] = detect_session.meta.weight
                    summary_temp['correct_pct'] = detect_session.stats.all_correct_percent
                    summary_temp['trial_count'] = detect_session.stats.all_trials
                    summary_temp['nogo_percent'] = detect_session.stats.nogo_percent
                    summary_temp['median_response_time'] = detect_session.stats.median_response_time
                    summary_temp['task'] = detect_session.meta.controller
                    summary_temp = {**summary_temp, **gsheet_dict}
                    summary_to_append.append(summary_temp)
                    
                    # cumulative data
                    session_data['session_no'] =  session_counter + 1
                    session_data['date'] = detect_session.meta.baredate
                    session_data['paradigm'] = gsheet_dict.get('paradigm','training_detection')
                    
                    cumul_data = cumul_data.append(session_data,ignore_index=True)
                    cumul_data['cumul_trial_no'] = np.arange(len(cumul_data)) + 1
                    session_counter += 1
                else:
                    display(f' >>> WARNING << NO DATA FOR SESSION {sesh[0]}')
                    continue
                
            if len(missing_sessions):
                cumul_data = get_running_stats(cumul_data,window_size=50)
                summary_data = summary_data.append(summary_to_append,ignore_index=True) 
                # adding the non-data stages of training once in the beginning
                if len(missing_sessions) == len(self.session_list):
                    non_data = self.get_non_data()
                    summary_data = summary_data.append(non_data,ignore_index=True)   
                # Failsafe date sorting for non-analyzed all trials and empty sessions(?)
                summary_data = summary_data.sort_values('date', ascending=True)
                summary_data.reset_index(inplace=True,drop=True)
  
        # turn date column to str
        summary_data['date']= summary_data['date'].apply(str)
        self.behavior_data.summary_data = summary_data
        self.behavior_data.cumul_data = cumul_data
            
    def save_behavior(self):
        """ Saves the behavior data """
        # save behavior data to the last session analysis folder
        self.save_data('detect')


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser(description='Wheel Behavior Data Parsing Tool')

    parser.add_argument('id',metavar='animalid',
                        type=str,help='Animal ID (e.g. KC020)')
    parser.add_argument('-d','--date',metavar='dateinterval',
                        type=str,help='Analysis start date (e.g. 191124)')
    parser.add_argument('-c','--criteria',metavar='criteria',default=[20,0],
                        type=str, help='Criteria dict for analysis thresholding, delimited list input')
    
    '''
    wheelbehave -d 200501 -c "20, 10" KC028
    '''

    opts = parser.parse_args()
    animalid = opts.id
    dateinterval = opts.date
    tmp = [int(x) for x in opts.criteria.split(',')]
    criteria = dict(answered_trials=tmp[0],
                    answered_correct=tmp[1])

    display('Updating Wheel Behavior for {0}'.format(animalid))
    display('Set criteria: {0}: {1}\n\t\t{2}: {3}'.format(list(criteria.keys())[0],
                                                  list(criteria.values())[0],
                                                  list(criteria.keys())[1],
                                                  list(criteria.values())[1]))
    w = WheelDetectionBehavior(animalid=animalid, dateinterval=dateinterval, criteria=criteria)

if __name__ == '__main__':
    main()
