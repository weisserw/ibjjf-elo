import { toast } from 'bulma-toast';
import { StringToNumber } from 'lodash';

const showToast = (message: string) => {
  toast({
    message,
    type: 'is-danger',
    dismissible: true,
    pauseOnHover: true,
    duration: 5000,
  });
}

export const axiosErrorToast = (error: any) => {
  if (error.response && error.response.data.error) {
    showToast(`Error: ${error.response.data.error}`);
  } else if (error.response) {
    showToast(`Error: ${error.response.status} - ${error.response.statusText}`);
  } else if (error.request) {
    showToast('Error: No response received from server');
  } else {
    showToast(`Error: ${error.message}`);
  }
}

export const immatureClass = (matchCount: number) => {
  if (matchCount <= 4) {
    return 'very-immature'
  } else if (matchCount <= 6) {
    return 'immature'
  } else {
    return ''
  }
}