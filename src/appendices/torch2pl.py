import torch.nn as nn
import torch
import pytorch_lightning as pl
import random
from utils import si_sdri_loss,save_wave,sir_loss
from barbar import Bar
from torch.utils.data import DataLoader
from termcolor import colored
import sys
import os
sys.path.append("/workspace/inputs/aviad/extraction/src/data")
from mydataloader import CreateFeatures



eps = torch.exp(torch.tensor(-6))



class Pl_module(pl.LightningModule):
    def __init__(self, model,hp,on_epoch_end_dir):
        super().__init__()
        self.model = model
        self.hp = hp
        self.on_epoch_end_dir = on_epoch_end_dir
        self.criterion = nn.MSELoss()

    def forward(self, mix,ref):
        y_hat = self.model( mix,ref)

        return y_hat
    def training_step(self, batch, batch_idx):

        mix, phase, ref1, target1, ref2, target2, target1_time,target2_time = batch

        if self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                    y1, y1_wrong = self(mix, ref1)
                    y2, y2_wrong = self(mix, ref2)
        elif not self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                    y1 = self(mix, ref1)
                    y2 = self(mix, ref2)
        elif self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                    y1, y1_wrong, y1_emb, y1_wrong_emb, ref1_vec = self(mix, ref1)
                    y2, y2_wrong, y2_emb, y2_wrong_emb, ref2_vec = self(mix, ref2)
        elif not self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                     y1, y1_emb, ref1_vec = self(mix, ref1)
                     y2, y2_emb, ref2_vec = self(mix, ref2)
        
        if self.hp.operation == 'mask':
            y1, y2 = mix * y1, mix * y2  

        if self.hp.criterion == 'mse' or self.hp.criterion == 'both':
            if self.hp.features == 'real_imag':
                Y1,Y2 = y1[:,0,:,:] + 1j*y1[:,1,:,:] , y2[:,0,:,:] + 1j*y2[:,1,:,:]
                Y1_log , Y2_log = torch.log10(torch.abs(Y1)+eps) , torch.log10(torch.abs(Y2)+eps)

                target1,target2 = target1[:,0,:,:] + 1j*target1[:,1,:,:] , target2[:,0,:,:] + 1j*target2[:,1,:,:]
                Target1_log , Target2_log = torch.log10(torch.abs(target1)+eps) ,  torch.log10(torch.abs(target2)+eps)
                target1 , target2 = Target1_log , Target2_log
                y1_ri , y2_ri = y1,y2
                y1,y2 = Y1_log , Y2_log
                

            loss = self.criterion(y1, target1) + self.criterion(y2, target2)
            

            if self.hp.full_negative_loss and self.hp.loss_with_wrong_speaker:
                loss += self.criterion(y1_wrong, target2) + self.criterion(y2_wrong, target1) + self.criterion(
                                        self.criterion(y1, y2), self.criterion(target1, target2)) + self.criterion(
                                        self.criterion(y1_wrong, y2_wrong), self.criterion(target1, target2))

            elif self.hp.full_negative_loss and not self.hp.loss_with_wrong_speaker:
                # loss += self.criterion(torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,mx, mn)) , torch.mean(si_sdri_loss(self.hp, mix, y2, target2_time, phase, mx, mn)))
                loss += self.criterion(self.criterion(y1, y2),self.criterion(target1, target2))

            elif not self.hp.full_negative_loss and self.hp.loss_with_wrong_speaker:
                loss += self.criterion(y1_wrong, target2) + self.criterion(y2_wrong, target1)

            if self.hp.TripletLoss:
                loss += self.criterion(y1_emb, ref1_vec) + self.criterion(y2_emb, ref2_vec) 
                # - self.criterion(y1_emb, ref2_vec) - self.criterion(y2_emb, ref1_vec)
                if self.hp.loss_with_wrong_speaker:
                    loss += self.criterion(y2_wrong_emb, ref1_vec) + self.criterion(y1_wrong_emb, ref2_vec) - self.criterion(
                            y2_wrong_emb, ref2_vec) - self.criterion(y1_wrong_emb, ref1_vec)

            if self.hp.criterion == 'both':
                loss = (1-self.hp.alpha) * loss
                if self.hp.features == 'real_imag':
                    loss += self.hp.alpha * ( torch.mean(si_sdri_loss(self.hp, mix, y1_ri, target1_time, phase,
                                               self.hp.features) + si_sdri_loss(self.hp, mix, y2_ri, target2_time, phase, self.hp.features)) )
                else:
                    loss += self.hp.alpha * ( torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,
                                               self.hp.features) + si_sdri_loss(self.hp, mix, y2, target2_time, phase, self.hp.features)) )
                


        elif self.hp.criterion == 'si_sdri':
            if self.hp.TripletLoss:
                loss = self.criterion(y1_emb, ref1_vec) + self.criterion(y2_emb, ref2_vec) 
                # - self.criterion(y1_emb, ref2_vec) - self.criterion(y2_emb, ref1_vec)
                if self.hp.loss_with_wrong_speaker:
                    loss += self.criterion(y2_wrong_emb, ref1_vec) + self.criterion(y1_wrong_emb, ref2_vec) - self.criterion(
                            y2_wrong_emb, ref2_vec) - self.criterion(y1_wrong_emb, ref1_vec)

                loss = (1-self.hp.alpha) * loss
                loss += self.hp.alpha * ( torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,
                                                    self.hp.features) + si_sdri_loss(self.hp, mix, y2, target2_time, phase, self.hp.features)) )
            else:
                loss = torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,
                                                    self.hp.features) + si_sdri_loss(self.hp, mix, y2, target2_time, phase, self.hp.features)) - torch.mean(si_sdri_loss(self.hp, mix, y2, target1_time, phase,
                                                    self.hp.features) - si_sdri_loss(self.hp, mix, y1, target2_time, phase, self.hp.features))
                if self.hp.loss_with_wrong_speaker:
                    loss = self.hp.alpha * loss
                    loss += (1-self.hp.alpha) * torch.mean(si_sdri_loss(self.hp, mix, y1_wrong, target2_time, phase,
                                                    self.hp.features) + si_sdri_loss(self.hp, mix, y2_wrong, target1_time, phase, self.hp.features))
                if self.hp.full_negative_loss:
                    loss = self.hp.alpha * loss
                    loss += (1-self.hp.alpha) * self.criterion(self.criterion(y1, y2),self.criterion(target1, target2))

        
        # elif self.hp.criterion == 'si_sdri_sir':    
        #     loss_si_sdri = torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,
        #                                             self.hp.features) + si_sdri_loss(self.hp, mix, y2, target2_time, phase, self.hp.features)) 
        #     loss_sir = sir_loss(self.hp,y1, target1_time, y2, target2_time)

        #     loss = loss_si_sdri + loss_sir
               
                    



        self.log('train_loss', loss)
        return loss

    def validation_step(self, batch, batch_idx):

        mix, phase, ref1, target1, ref2, target2, target1_time,target2_time = batch
        
        rnd_int = random.randint(0, 1)
        ref = ref1 if rnd_int else ref2
        target = target1 if rnd_int else target2
        target_time = target1_time if rnd_int else target2_time

        if  self.hp.criterion == 'si_sdri_sir':  
            y1 = self(mix, ref1)
            y2 = self(mix, ref2)
        else:
            if self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                        y, _ = self(mix, ref)
            elif not self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                        y = self(mix, ref)
            elif self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                        y, _, _, _, _ = self(mix, ref)
            elif not self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                        y, _, _ = self(mix, ref)

            if self.hp.operation == 'mask':
                y= mix * y 

        if self.hp.criterion == 'mse':
            loss = self.criterion(y, target)
            self.log('val_loss', loss)
        elif self.hp.criterion == 'si_sdri':
            loss = si_sdri_loss(self.hp, mix, y, target_time, phase,self.hp.features)
            self.log('val_loss', loss)

        elif self.hp.criterion == 'both':
            if self.hp.features == 'real_imag':
                Y = y[0,:,:] + 1j*y[1,:,:]
                Y_log = torch.log10(torch.abs(Y)+eps)
                Target_log = torch.log10(torch.abs(target)+eps)
            else:
                Y_log = y
                Target_log = target

            loss_mse =  self.criterion(Y_log, Target_log) 
            loss_si_sdri =  si_sdri_loss(self.hp, mix, y, target_time, phase, self.hp.features)
            loss = (1-self.hp.alpha) * loss_mse + self.hp.alpha * loss_si_sdri

            self.log('val_loss_mse', loss_mse)
            self.log('val_loss_si_sdri', loss_si_sdri)
            self.log('val_loss', loss)
  
        # elif self.hp.criterion == 'si_sdri_sir':    
        #     loss_si_sdri = torch.mean(si_sdri_loss(self.hp, mix, y1, target1_time, phase,
        #                                             self.hp.features) + si_sdri_loss(self.hp, mix, y2, target2_time, phase, self.hp.features)) 
        #     loss_sir = sir_loss(self.hp,y1, target1_time, y2, target2_time)

        #     loss = loss_si_sdri + loss_sir


        #     self.log('val_loss_sir', loss_sir)
        #     self.log('val_loss_si_sdri', loss_si_sdri)
        #     self.log('val_loss', loss)
               
        
        return loss

    def configure_optimizers(self):
        if self.hp.train.optimizer == 'adam':
            optimizer = torch.optim.Adam(self.parameters(),lr=self.hp.train.lr)
        if self.hp.train.optimizer == 'sgd':
            optimizer = torch.optim.SGD(self.parameters(),lr=self.hp.train.lr)
        return {'optimizer': optimizer}

    def on_epoch_end(self):
        if(self.current_epoch == 0):
            ic = self.hp.unet.inputchannels*2 if  self.hp.features == 'real_imag' else self.hp.unet.inputchannels
            sampleMix = torch.rand(
                (ic, self.hp.num_of_frames, self.hp.num_of_frames),dtype=torch.complex64,device = self.device)
            sampleRef = torch.rand(
                (ic, self.hp.num_of_emb_frames, self.hp.num_of_emb_frames),dtype=torch.complex64,device = self.device)
            self.logger.experiment.add_graph(
                Pl_module(self.model,self.hp,self.on_epoch_end_dir), (sampleMix, sampleRef))

        if self.hp.database == 'wsj':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/wsj_no_reverberant_for_test'
        elif self.hp.database == 'wsj_rvrb':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/wsj_reverberant_for_test'
        elif self.hp.database == 'libri':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/no_reverberation_for_test'
        elif self.hp.database == 'libri_rvrb':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/reverberant_for_test'
        elif self.hp.database == 'both':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/both_no_reverberant_for_test'
        elif self.hp.database == 'both_rvrb':
            test_dir = '/workspace/inputs/aviad/extraction/data/generated_files/both_reverberant_for_test'

        test_set = CreateFeatures(self.hp, test_dir, 1, train_mode=False)
        testloader = DataLoader(test_set, batch_size=1, shuffle=False,
                                num_workers=self.hp.dataloader.num_workers, pin_memory=self.hp.dataloader.pin_memory)
        i = 0
        for (Mix_mag, Mix_phase, Ref_mag, Target_mag, mx, mn, Target_phase, Ref, Ref_wrong, Ref_mag_wrong, Mix_mag_wrong, Mix_phase_wrong, tar, tar_wrong) in Bar(testloader):
            print(colored('\t on epoch end number {}', 'green').format(i))
            if Mix_mag.shape[2] < 130:
                print(colored('\t jump happend in {}', 'green').format(i))
                continue
            else:
                i += 1
            dir = os.path.join(
                self.on_epoch_end_dir, 'scenario_{0}/'.format(i))
            if not os.path.exists(dir):
                os.makedirs(dir,exist_ok=True)
            Mix_mag, Ref_mag, Mix_phase = Mix_mag.to(self.device), Ref_mag.to(
                self.device), Mix_phase.to(self.device)

            if self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                    Y_mag, _ = self(Mix_mag, Ref_mag)
            elif not self.hp.loss_with_wrong_speaker and not self.hp.TripletLoss:
                    Y_mag = self(Mix_mag, Ref_mag)
            elif self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                    Y_mag, _, _, _, _ = self(Mix_mag, Ref_mag)
            elif not self.hp.loss_with_wrong_speaker and self.hp.TripletLoss:
                    Y_mag, _, _ = self(Mix_mag, Ref_mag)

            if self.hp.criterion =='si_sdri' or  self.hp.criterion =='both':
                if not self.hp.features == 'real_imag':
                    mx, mn = torch.max(Mix_mag), torch.min(Mix_mag) 
                    mx_y, mn_y = torch.max(Y_mag), torch.min(Y_mag)
                    Y_mag = (mx-mn)*(Y_mag-mn_y)/(mx_y-mn_y)+mn

         

            phase = torch.squeeze(Mix_phase)
            Y = Y_mag[0,:,:] + 1j*Y_mag[1,:,:]
            y = torch.istft(Y, n_fft=self.hp.stft.fft_length,
                            hop_length=self.hp.stft.fft_hop)
            save_wave(y.cpu(), os.path.join(dir, 'output.wav'))