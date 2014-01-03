<?php session_start();
if(!isset($_SESSION['userid'])){
	unset($_SESSION['userid']);
    unset($_SESSION['username']);
    header("Location:login.php");
}
?>